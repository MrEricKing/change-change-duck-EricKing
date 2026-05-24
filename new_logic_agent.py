# -*- coding: utf-8 -*-
import os
import json
import time
import argparse
import hashlib
import subprocess
import shutil
import tempfile
from pathlib import Path

import requests


CHAT_API_URL = "https://api.openai-next.com/v1/chat/completions"
CHAT_MODEL = "gpt-4o-mini"
MAX_KNOWLEDGE_CHARS = 5000
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output_multi_video"
CACHE_DIR = BASE_DIR / "output" / "video_cache"


# Whisper / OCR 模型单例（首次调用懒加载，跨视频复用）
import threading as _threading
_WHISPER_LOCK = _threading.Lock()
_WHISPER_MODEL = None
_OCR_LOCK = _threading.Lock()
_OCR_MODEL = None


def _get_whisper_model():
    """跨视频复用 Whisper 模型实例。

    可用环境变量调：
      WHISPER_MODEL  - tiny / base / small / medium（默认 small；本地已缓存。想更快可设 base，但需要网络下载）
      WHISPER_DEVICE - cpu / cuda
      WHISPER_COMPUTE- int8 / int8_float16 / float16
    """
    global _WHISPER_MODEL
    if _WHISPER_MODEL is not None:
        return _WHISPER_MODEL
    with _WHISPER_LOCK:
        if _WHISPER_MODEL is not None:
            return _WHISPER_MODEL
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise RuntimeError("缺少 faster-whisper，请运行：pip install faster-whisper")
        size = os.getenv("WHISPER_MODEL", "small")
        device = os.getenv("WHISPER_DEVICE", "cpu")
        compute = os.getenv("WHISPER_COMPUTE", "int8")
        # cpu_threads=0 → 让 CTranslate2 自己选；显式给个上限避免抢占太狠
        cpu_threads = int(os.getenv("WHISPER_CPU_THREADS", "0"))
        print(f"加载 Whisper 模型（一次性）：size={size} device={device} compute={compute}")
        _WHISPER_MODEL = WhisperModel(
            size, device=device, compute_type=compute,
            cpu_threads=cpu_threads or 0,
        )
        return _WHISPER_MODEL


def _get_ocr_model():
    """跨视频复用 OCR 模型实例。"""
    global _OCR_MODEL
    if _OCR_MODEL is not None:
        return _OCR_MODEL
    with _OCR_LOCK:
        if _OCR_MODEL is not None:
            return _OCR_MODEL
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError:
            return None
        print("加载 OCR 模型（一次性）...")
        _OCR_MODEL = RapidOCR()
        return _OCR_MODEL


SYSTEM_PROMPT = """
你是一个多视频中文旅行规划 AI Agent。你会收到多个旅游博主视频提取出的 ASR 文本、OCR 文本、视频元数据，以及用户的基础旅行约束和可能追加的二次修改要求。

你的任务不是把视频里所有景点都列出来，而是把视频里提到的地点当作候选池，结合用户的天数、人数、预算、旅行强度、适合人群、兴趣偏好、体力情况和用户额外要求，筛选出真正值得、顺路、可执行的旅行路线。

【用户要求优先级 · 最高优先级】
1. 用户输入的额外要求优先级最高，高于视频博主推荐、高于默认路线偏好。
2. 如果用户说“不想爬山 / 不要太累 / 少走路 / 不想早起”，必须降低体力消耗，避免山、长台阶、大跨度步行、频繁换乘和太早开始的安排。
3. 如果用户说“想多吃东西 / 美食多一点 / 小吃多一点”，必须增加餐饮、小吃、夜市、咖啡甜品等 stops，并在 summary.notes 说明美食路线逻辑。
4. 如果用户说“想拍照 / 出片 / 夜景 / 海边 / 地标”，必须优先安排上镜、夜景、地标、海边、展馆、街区类地点。
5. 如果用户说“少花钱 / 预算低 / 不想买门票”，必须减少高门票、高消费、打车和商业项目，优先免费景点和公共交通。
6. 如果用户说“带老人 / 带小孩 / 亲子”，必须降低强度，增加休息点，避免过多换乘、爬坡、排队久的项目。
7. 如果用户说“不要某类地点”或“不要某个地点”，这些点禁止进入 itinerary，应放入 avoid_list 或 backup_list，并写明原因。
8. 如果用户说“必须去某个地点”，只要该地点属于当前城市/区域且路线可执行，应优先放入 itinerary.stops，并在 reason 中说明满足了用户要求。
9. 如果用户要求和视频候选池冲突，优先满足用户要求；但不要编造完全无关城市的地点。
10. 每个 stop 的 reason 必须体现为什么符合用户要求，例如“用户要求不要太累，因此安排同片区步行串联”。

必须遵守：
1. 视频中提到的地点不是都要去，必须筛选；不顺路、与用户偏好或额外要求不符的放入 backup_list，而不是 itinerary。
2. 每天路线要按区域聚类，减少折返和跨区域移动。
3. 轻松型每天 2-3 个 stops；标准型每天 3-4 个 stops；特种兵型每天 4-5 个 stops；老人/亲子必须降低体力消耗。
4. 地点必须属于当前城市/区域；如果当前城市是东京，不能安排台湾、中国大陆、香港等同名地点。
5. 地点有重名时，优先结合 city、OCR、ASR 和用户要求上下文判断；无法确认属于当前城市就放入 backup_list，不要放入 itinerary。
6. itinerary 不能为空。
7. 每一天必须包含 stops。
8. 每个 day 至少安排 2 个 stops，最多 5 个 stops。
9. must_go 只是推荐清单，不等于主路线；真正路线必须写进 itinerary.stops。
10. must_go 和 avoid_list 必须写成对象数组，每项包含 place 和 reason，不要只写字符串。
11. 每个 stop 的 transport 必须写清交通方式和预计时间，例如“地铁银座线 + 步行 · 约18分钟”“公交 23 路 · 约25分钟”“步行 · 约8分钟”；不能只写“地铁/公交/步行”。
12. 只能输出严格 JSON，不要 Markdown，不要解释，不要代码块。
13. 如果某个地点定位失败、明显不属于当前城市、或不符合用户额外要求，不要强行放入计划，应放入 backup_list 或 avoid_list，并说明原因。
14. 输出 summary.route_logic 必须说明路线动线如何减少折返，以及如何满足用户额外要求。
15. 输出 summary.notes 必须提到用户额外要求对路线筛选的影响；如果用户额外要求为“无”，则写常规注意事项。

输出 JSON 格式必须如下：

{
  "title": "旅行攻略标题",
  "city": "核心城市",
  "days": 3,
  "people": 2,
  "budget_total": 3000,
  "travel_style": "轻松型",
  "target_group": "大人",
  "itinerary": [
    {
      "day": 1,
      "theme": "当天主题",
      "stops": [
        {
          "place": "地点名称",
          "type": "景点/餐饮/购物/交通/住宿/休闲",
          "activities": ["活动1", "活动2"],
          "time_hours": 2,
          "cost": 100,
          "transport": "地铁/公交/步行/打车 + 预计时间，例如 地铁银座线 + 步行 · 约18分钟",
          "reason": "为什么安排这里；如何顺路；如何满足用户额外要求",
          "tip": "实用建议",
          "avoid": false,
          "source_hint": "来自哪些视频线索；如果来自用户额外要求，写用户额外要求"
        }
      ]
    }
  ],
  "must_go": [
    {"place": "最值得去的点", "reason": "为什么必去；如何符合用户需求"}
  ],
  "avoid_list": [
    {"place": "明确不推荐点", "reason": "为什么避雷；是否因为不符合用户要求"}
  ],
  "backup_list": [
    {
      "place": "候选但未安排地点",
      "reason": "为什么不放入主路线，例如不顺路/太累/不符合用户要求/定位不确定"
    }
  ],
  "summary": {
    "total_cost": 3000,
    "route_logic": "路线筛选和动线逻辑，并说明如何满足用户额外要求",
    "notes": "注意事项，以及用户额外要求对路线的影响"
  }
}
"""


def ensure_cmd(cmd):
    return shutil.which(cmd) is not None


def run_cmd(cmd):
    print("运行命令：", " ".join(map(str, cmd)))
    subprocess.run(cmd, check=True)


def video_cache_key(video_path: Path):
    stat = video_path.stat()
    raw = f"{video_path.resolve()}_{stat.st_size}_{stat.st_mtime}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def load_video_cache(video_path: Path):
    CACHE_DIR.mkdir(exist_ok=True)
    key = video_cache_key(video_path)
    cache_path = CACHE_DIR / f"{key}.json"

    if cache_path.exists():
        print("发现缓存，直接读取：", cache_path)
        return json.loads(cache_path.read_text(encoding="utf-8"))

    return None


def save_video_cache(video_path: Path, data: dict):
    CACHE_DIR.mkdir(exist_ok=True)
    key = video_cache_key(video_path)
    cache_path = CACHE_DIR / f"{key}.json"

    cache_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("已保存视频解析缓存：", cache_path)


def extract_audio(video_path: Path, work_dir: Path) -> Path:
    if not ensure_cmd("ffmpeg"):
        raise RuntimeError("缺少 ffmpeg，请先安装 FFmpeg，并确保命令行能运行 ffmpeg")

    audio_path = work_dir / f"{video_path.stem}_audio.wav"

    run_cmd([
        "ffmpeg",
        "-y",
        "-i", str(video_path),
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        str(audio_path)
    ])

    return audio_path


def transcribe_audio_local(audio_path: Path) -> str:
    model = _get_whisper_model()

    print("开始语音转文字...")
    # 单例并发安全：CTranslate2 内部线程池可并发，但同一个 model 同时被多个线程
    # 调用 transcribe 时官方建议加锁，避免 segment 输出混淆。
    with _WHISPER_LOCK:
        segments, _ = model.transcribe(
            str(audio_path),
            language="zh",
            beam_size=int(os.getenv("WHISPER_BEAM", "1")),  # 默认贪心，比 beam=5 快 ~3x
            vad_filter=True,                                # 跳过静音段，大幅压时
            vad_parameters={"min_silence_duration_ms": 500},
            condition_on_previous_text=False,               # 关掉历史条件，避免长视频漂移并提速
        )
        text = "".join(seg.text for seg in segments)
    return text.strip()


def extract_keyframes(video_path: Path, frame_dir: Path, every_seconds=2.0, max_frames=40):
    import cv2

    frame_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"视频打开失败：{video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    if fps <= 0:
        fps = 25

    duration = total_frames / fps
    frame_paths = []

    t = 0.0
    idx = 0

    while t < duration and len(frame_paths) < max_frames:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()

        if ok:
            out_path = frame_dir / f"{video_path.stem}_frame_{idx:04d}_{int(t)}s.jpg"
            cv2.imwrite(str(out_path), frame)
            frame_paths.append(out_path)
            idx += 1

        t += every_seconds

    cap.release()
    return frame_paths


def ocr_frames(frame_paths):
    ocr = _get_ocr_model()
    if ocr is None:
        print("未安装 rapidocr-onnxruntime，跳过 OCR。")
        return []

    all_texts = []
    # 同一个 OCR 实例不是线程安全 → 跨视频并发时串行化
    with _OCR_LOCK:
        for img_path in frame_paths:
            try:
                result, _ = ocr(str(img_path))
                if not result:
                    continue

                for item in result:
                    if len(item) >= 3:
                        text = str(item[1]).strip()
                        score = float(item[2])
                        if score >= 0.45 and len(text) >= 2:
                            all_texts.append(text)

            except Exception as e:
                print(f"OCR失败：{img_path}，原因：{e}")

    seen = set()
    dedup = []

    for t in all_texts:
        if t not in seen:
            seen.add(t)
            dedup.append(t)

    return dedup


def build_video_fused_text(filename, transcript, ocr_lines):
    return f"""
【视频文件】
{filename}

【语音转写】
{transcript}

【OCR识别】
{"；".join(ocr_lines)}

【解析说明】
- 语音转写用于理解路线、顺序、评价、推荐和避雷。
- OCR 用于修正景点名、店名、站名、路牌、字幕。
"""


def analyze_one_video(video_path: Path, every_seconds=2.0, max_frames=40, check_cancel=None):
    cached = load_video_cache(video_path)
    if cached:
        return cached

    def _check():
        if check_cancel:
            check_cancel()

    work_dir = Path(tempfile.mkdtemp(prefix="multi_video_agent_"))

    try:
        print("\n==============================")
        print("正在解析视频：", video_path)
        print("==============================")

        _check()
        audio_path = extract_audio(video_path, work_dir)
        _check()
        transcript = transcribe_audio_local(audio_path)

        _check()
        frame_dir = work_dir / "frames"
        frame_paths = extract_keyframes(
            video_path,
            frame_dir,
            every_seconds=every_seconds,
            max_frames=max_frames
        )

        _check()
        ocr_lines = ocr_frames(frame_paths)

        data = {
            "filename": video_path.name,
            "video_path": str(video_path),
            "transcript": transcript,
            "ocr_lines": ocr_lines,
            "fused_text": build_video_fused_text(video_path.name, transcript, ocr_lines)
        }

        save_video_cache(video_path, data)
        return data

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def build_all_fused_text(videos_data):
    parts = []

    for i, v in enumerate(videos_data, start=1):
        parts.append(f"\n========== 视频 {i} ==========")
        parts.append(v.get("fused_text", ""))

    return "\n".join(parts)


def make_requirements(days, people, budget, style, group, extra):
    return f"""
天数：{days}
人数：{people}
总预算：{budget}
旅行强度：{style}
适合人群：{group}
额外要求（必须优先满足；如果为“无”则按基础约束规划）：{extra or "无"}
"""


def call_llm(api_key, knowledge_text, user_requirements):
    knowledge_text = knowledge_text[:MAX_KNOWLEDGE_CHARS]

    body = {
        "model": CHAT_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"""
【多个旅游博主视频提取信息】
{knowledge_text}

【用户当前约束与偏好】
{user_requirements}

请基于以上信息，生成最终旅行方案 JSON。
"""
            }
        ],
        "temperature": 0.2
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }

    print("\n正在调用大模型生成最终旅行方案，模型：", CHAT_MODEL)

    session = requests.Session()
    session.trust_env = False

    response = session.post(
        CHAT_API_URL,
        headers=headers,
        json=body,
        timeout=180,
        proxies={"http": "", "https": ""}
    )

    if response.status_code != 200:
        raise RuntimeError(f"大模型 API 请求失败：{response.status_code}\n{response.text}")

    data = response.json()
    content = data["choices"][0]["message"]["content"].strip()

    if content.startswith("```json"):
        content = content.replace("```json", "").replace("```", "").strip()
    elif content.startswith("```"):
        content = content.replace("```", "").strip()

    try:
        return validate_plan(json.loads(content))
    except json.JSONDecodeError:
        raise RuntimeError("模型返回的不是合法 JSON：\n" + content)


def validate_plan(plan):
    itinerary = plan.get("itinerary", [])
    if not itinerary:
        raise RuntimeError("模型返回的 itinerary 为空，无法生成地图")

    for day in itinerary:
        if not day.get("stops"):
            raise RuntimeError(f"第 {day.get('day')} 天 stops 为空，无法生成地图")

    return plan


def render_markdown(plan):
    lines = []

    lines.append(f"# {plan.get('title', '旅行攻略')}")
    lines.append(f"- 城市：{plan.get('city', '')}")
    lines.append(f"- 天数：{plan.get('days', '')}")
    lines.append(f"- 人数：{plan.get('people', '')}")
    lines.append(f"- 总预算：¥{plan.get('budget_total', '')}")
    lines.append(f"- 风格：{plan.get('travel_style', '')}")
    lines.append(f"- 适合人群：{plan.get('target_group', '')}")
    lines.append("")

    for day in plan.get("itinerary", []):
        lines.append(f"## 第{day.get('day', '')}天 · {day.get('theme', '')}")

        for stop in day.get("stops", []):
            lines.append(
                f"- **{stop.get('place', '')}**"
                f"｜{stop.get('type', '')}"
                f"｜{stop.get('time_hours', '')}小时"
                f"｜约¥{stop.get('cost', '')}"
            )

            if stop.get("activities"):
                lines.append(f"  - 活动：{'、'.join(stop.get('activities', []))}")
            if stop.get("transport"):
                lines.append(f"  - 交通：{stop.get('transport')}")
            if stop.get("reason"):
                lines.append(f"  - 安排理由：{stop.get('reason')}")
            if stop.get("tip"):
                lines.append(f"  - Tips：{stop.get('tip')}")
            if stop.get("source_hint"):
                lines.append(f"  - 视频线索：{stop.get('source_hint')}")

        lines.append("")

    def _fmt_duo(x):
        if isinstance(x, dict):
            place = x.get("place") or x.get("name") or ""
            reason = x.get("reason") or x.get("note") or ""
            return f"**{place}** — {reason}" if (place and reason) else (place or reason or "")
        return str(x)

    if plan.get("must_go"):
        lines.append("## 必去清单")
        for x in plan["must_go"]:
            lines.append(f"- {_fmt_duo(x)}")
        lines.append("")

    if plan.get("avoid_list") or plan.get("avoid"):
        lines.append("## 避雷清单")
        for x in (plan.get("avoid_list") or plan.get("avoid") or []):
            lines.append(f"- {_fmt_duo(x)}")
        lines.append("")

    if plan.get("backup_list"):
        lines.append("## 候选但未安排")
        for item in plan["backup_list"]:
            if isinstance(item, dict):
                lines.append(f"- {item.get('place', '')}：{item.get('reason', '')}")
            else:
                lines.append(f"- {item}")
        lines.append("")

    summary = plan.get("summary", {})
    lines.append("---")
    lines.append(f"**总预算估算**：¥{summary.get('total_cost', '')}")
    lines.append(f"**路线逻辑**：{summary.get('route_logic', '')}")
    lines.append(summary.get("notes", ""))

    return "\n".join(lines)


def guess_country_code(city):
    if city in ["东京", "大阪", "京都", "札幌", "福冈", "名古屋", "横滨"]:
        return "jp"
    if city in ["上海", "北京", "杭州", "成都", "广州", "深圳", "重庆", "西安", "福州", "平潭", "福建", "厦门", "泉州"]:
        return "cn"
    return None


def geocode_place(place, city_hint=""):
    from geopy.geocoders import Nominatim

    geolocator = Nominatim(user_agent="multi_video_travel_agent", timeout=5)

    country_code = guess_country_code(city_hint)

    queries = []

    if city_hint:
        queries.append(f"{city_hint} {place}")
        queries.append(f"{place} {city_hint}")
        queries.append(f"{place} {city_hint} 日本")
        queries.append(f"{city_hint} {place} Japan")

    queries.append(place)

    for q in queries:
        try:
            kwargs = {
                "query": q,
                "timeout": 5,
                "language": "zh"
            }

            if country_code:
                kwargs["country_codes"] = country_code

            loc = geolocator.geocode(**kwargs)

            if loc:
                return loc.latitude, loc.longitude, loc.address

        except Exception as e:
            # 连接被拒 / 超时：整站不可达，直接放弃后续 query，避免重试日志噪音
            msg = str(e).lower()
            if ("connection" in msg or "refused" in msg or "timed out" in msg
                    or "name or service" in msg or "10061" in msg):
                print(f"Nominatim 不可达，跳过：{e}")
                return None
            continue

    return None


# ----------------------- LLM 批量地理编码（兜底，全球可用） -----------------------
def geocode_places_llm_batch(places, city_hint, api_key, base_url="", model=""):
    """让 LLM 一次性给所有地点输出 WGS84 (lat,lng)。返回 {place: (lat,lng)}。"""
    if not places or not api_key:
        return {}
    base_url = base_url or "https://api.openai-next.com"
    model = model or CHAT_MODEL
    url = base_url.rstrip("/") + "/v1/chat/completions"
    prompt = (
        f"以下是『{city_hint or '未知地区'}』的景点 / 店铺 / 打卡点列表。\n"
        f"请输出每个地点的 **WGS84 GPS 坐标**（普通经纬度，不是火星坐标），\n"
        f"严格返回 JSON 对象：键为地点名（与输入完全一致），值为 [lat, lng] 数组。\n"
        f"如果某地点无法定位，值写 null。不要任何额外解释或代码块。\n\n"
        f"地点列表：{json.dumps(places, ensure_ascii=False)}"
    )
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是熟悉全球地理坐标的助手。只输出严格 JSON。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
    }
    try:
        session = requests.Session()
        session.trust_env = False
        r = session.post(url, headers=headers, json=body, timeout=90,
                         proxies={"http": "", "https": ""})
        if r.status_code != 200 and "response_format" in r.text:
            body.pop("response_format", None)
            r = session.post(url, headers=headers, json=body, timeout=90,
                             proxies={"http": "", "https": ""})
        if r.status_code != 200:
            print(f"LLM 地理编码失败 {r.status_code}：{r.text[:200]}")
            return {}
        content = r.json()["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.strip("`")
            if content.lower().startswith("json"):
                content = content[4:].lstrip()
        coords = json.loads(content)
        out = {}
        for k, v in coords.items():
            if isinstance(v, (list, tuple)) and len(v) == 2:
                try:
                    out[k] = (float(v[0]), float(v[1]))
                except (TypeError, ValueError):
                    pass
        return out
    except Exception as e:
        print(f"LLM 地理编码异常：{e}")
        return {}
def make_single_route_map(plan, out_html, api_key="", base_url="", model=""):
    import folium
    import time
    from folium.plugins import AntPath

    points = []
    city_hint = plan.get("city", "")

    print("\n开始地理编码并生成单张路线地图...")

    # ---------- 收集所有需要定位的地点 ----------
    place_stops = []  # [(day, stop, place)]
    for day in plan.get("itinerary", []):
        for stop in day.get("stops", []):
            place = (stop.get("place") or "").strip()
            if not place:
                continue
            place_stops.append((day, stop, place))

    # ---------- 第一遍：LLM 批量定位（全球可用，避开 Nominatim 不通的环境） ----------
    unique_places = []
    seen = set()
    for _, _, p in place_stops:
        if p not in seen:
            seen.add(p)
            unique_places.append(p)

    llm_coords = {}
    if api_key and unique_places:
        print(f"LLM 批量定位 {len(unique_places)} 个地点（city={city_hint}）...")
        llm_coords = geocode_places_llm_batch(unique_places, city_hint, api_key, base_url, model)
        print(f"LLM 成功 {len(llm_coords)} / {len(unique_places)}")

    # ---------- 第二遍：剩下的用 Nominatim 兜底（连接不通时会快速放弃） ----------
    nominatim_dead = False
    for day, stop, place in place_stops:
        # 1. stop 上已有坐标（极少见，但兼容）
        try:
            lat = float(stop.get("lat")); lng = float(stop.get("lng"))
            address = stop.get("address", "")
        except (TypeError, ValueError):
            lat = lng = None
            address = ""

        # 2. LLM 给的坐标
        if lat is None or lng is None:
            if place in llm_coords:
                lat, lng = llm_coords[place]
                address = ""

        # 3. Nominatim 兜底（仅当还没拿到 + Nominatim 还活着）
        if (lat is None or lng is None) and not nominatim_dead:
            print("定位（Nominatim）：", place)
            result = geocode_place(place, city_hint=city_hint)
            time.sleep(0.6)
            if result is None:
                # geocode_place 返回 None 可能是连接被拒 — 标记不再尝试
                nominatim_dead = True
            else:
                lat, lng, address = result

        if lat is None or lng is None:
            print("定位失败：", place)
            continue

        # 回填到 plan 本身，方便后续渲染 / 路线优化用到
        stop["lat"] = lat
        stop["lng"] = lng
        if address and not stop.get("address"):
            stop["address"] = address

        points.append({
            "day": day.get("day", ""),
            "place": place,
            "lat": lat,
            "lng": lng,
            "address": address,
            "type": stop.get("type", ""),
            "activities": "、".join(stop.get("activities", [])),
            "transport": stop.get("transport", ""),
            "reason": stop.get("reason", ""),
            "tip": stop.get("tip", ""),
            "time_hours": stop.get("time_hours", ""),
            "cost": stop.get("cost", "")
        })

    if not points:
        print("没有成功定位的景点，无法生成地图")
        return []

    center_lat = sum(p["lat"] for p in points) / len(points)
    center_lng = sum(p["lng"] for p in points) / len(points)

    m = folium.Map(
        location=[center_lat, center_lng],
        zoom_start=12,
        tiles="OpenStreetMap"
    )

    day_groups = {}
    for p in points:
        day_groups.setdefault(p["day"], []).append(p)

    global_index = 1

    for day, day_points in day_groups.items():
        coords = []

        for p in day_points:
            coords.append([p["lat"], p["lng"]])

            popup_html = f"""
            <b>{global_index}. 第{p['day']}天：{p['place']}</b><br>
            类型：{p['type']}<br>
            活动：{p['activities']}<br>
            交通：{p['transport']}<br>
            理由：{p['reason']}<br>
            Tips：{p['tip']}<br>
            <small>{p['address']}</small>
            """

            marker_card_html = f"""
            <div style="
                position:relative;
                width:310px;
                height:132px;
                font-family:Microsoft YaHei, PingFang SC, sans-serif;
            ">
                <!-- 真正的定位点 -->
                <div style="
                    position:absolute;
                    left:0px;
                    top:44px;
                    width:32px;
                    height:32px;
                    border-radius:50%;
                    background:#2563eb;
                    color:white;
                    line-height:32px;
                    text-align:center;
                    font-weight:900;
                    border:3px solid white;
                    box-shadow:0 4px 10px rgba(0,0,0,0.28);
                    z-index:3;
                ">
                    {global_index}
                </div>

                <!-- 连接小线 -->
                <div style="
                    position:absolute;
                    left:31px;
                    top:60px;
                    width:22px;
                    height:3px;
                    background:#2563eb;
                    border-radius:99px;
                    z-index:2;
                "></div>

                <!-- 海报信息卡片：固定在 marker 右侧 -->
                <div style="
                    position:absolute;
                    left:52px;
                    top:0px;
                    width:245px;
                    min-height:118px;
                    background:#fffaf0;
                    border:2px solid #e8d2a4;
                    border-radius:20px;
                    padding:12px 14px;
                    box-shadow:0 8px 18px rgba(82,58,24,0.20);
                    color:#243042;
                    transform:rotate(-1deg);
                    z-index:1;
                ">
                    <div style="
                        display:flex;
                        align-items:center;
                        gap:8px;
                        margin-bottom:7px;
                    ">
                        <div style="
                            font-size:17px;
                            font-weight:900;
                            line-height:1.2;
                            max-width:150px;
                            word-break:break-all;
                        ">
                            {p['place']}
                        </div>

                        <div style="
                            margin-left:auto;
                            background:#ffe7ac;
                            border:1px solid #edc76e;
                            color:#80571c;
                            border-radius:999px;
                            padding:3px 8px;
                            font-size:12px;
                            font-weight:800;
                            white-space:nowrap;
                        ">
                            {p['type']}
                        </div>
                    </div>

                    <div style="
                        font-size:13px;
                        line-height:1.58;
                    ">
                        <b>活动：</b>{p['activities']}<br>
                        <b>时间：</b>{p['time_hours']} h　
                        <b>预算：</b>¥{p['cost']}<br>
                        <b>交通：</b>{p['transport']}<br>
                        <b>Tips：</b>{p['tip']}
                    </div>
                </div>
            </div>
            """

            folium.Marker(
                location=[p["lat"], p["lng"]],
                popup=popup_html,
                tooltip=f"{global_index}. 第{p['day']}天 {p['place']}",
                icon=folium.DivIcon(
                    icon_size=(310, 132),
                    icon_anchor=(16, 60),
                    html=marker_card_html
                )
            ).add_to(m)

            global_index += 1

        if len(coords) >= 2:
            AntPath(
                locations=coords,
                color="#2563eb",
                pulse_color="#ffffff",
                weight=5,
                opacity=0.85,
                delay=800,
                dash_array=[12, 20],
            ).add_to(m)

    m.save(str(out_html))
    print("地图已保存：", out_html)

    return points


def save_outputs(plan, knowledge_text):
    OUTPUT_DIR.mkdir(exist_ok=True)

    markdown = render_markdown(plan)

    plan_json_path = OUTPUT_DIR / "final_plan.json"
    plan_md_path = OUTPUT_DIR / "final_plan.md"
    knowledge_path = OUTPUT_DIR / "multi_video_knowledge.txt"
    map_path = OUTPUT_DIR / "route_map.html"
    points_path = OUTPUT_DIR / "geocoded_points.json"

    knowledge_path.write_text(knowledge_text, encoding="utf-8")
    plan_json_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    plan_md_path.write_text(markdown, encoding="utf-8")

    points = make_single_route_map(plan, map_path)
    points_path.write_text(json.dumps(points, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n========== 当前旅行方案 ==========\n")
    print(markdown)
    print("\n=================================\n")

    print("已保存融合知识：", knowledge_path)
    print("已保存 JSON：", plan_json_path)
    print("已保存攻略：", plan_md_path)
    print("已保存地图：", map_path)
    print("已保存地图点：", points_path)


def interactive_loop(api_key, knowledge_text):
    print("\n进入交互式重规划模式。")
    print("输入新需求会重新规划并覆盖 route_map.html。输入 q 退出。\n")

    while True:
        user_req = input("请输入新的旅行需求：").strip()

        if user_req.lower() in ["q", "quit", "exit"]:
            print("退出交互模式。")
            break

        if not user_req:
            continue

        plan = call_llm(api_key, knowledge_text, user_req)
        save_outputs(plan, knowledge_text)


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--videos", nargs="+", required=True, help="多个本地视频路径")
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--people", type=int, default=2)
    parser.add_argument("--budget", type=float, default=3000)
    parser.add_argument("--style", default="轻松型")
    parser.add_argument("--group", default="大人")
    parser.add_argument("--extra", default="无")
    parser.add_argument("--every-seconds", type=float, default=2.0)
    parser.add_argument("--max-frames", type=int, default=40)
    parser.add_argument("--api-key", default=os.getenv("VECTRUST_API_KEY", ""))
    parser.add_argument("--interactive", action="store_true")

    args = parser.parse_args()

    if not args.api_key:
        raise RuntimeError("缺少 VECTRUST_API_KEY，请先设置环境变量")

    videos_data = []

    for p in args.videos:
        video_path = Path(p)

        if not video_path.exists():
            raise FileNotFoundError(f"找不到视频文件：{video_path}")

        video_data = analyze_one_video(
            video_path,
            every_seconds=args.every_seconds,
            max_frames=args.max_frames
        )

        videos_data.append(video_data)

    knowledge_text = build_all_fused_text(videos_data)

    requirements = make_requirements(
        days=args.days,
        people=args.people,
        budget=args.budget,
        style=args.style,
        group=args.group,
        extra=args.extra
    )

    plan = call_llm(args.api_key, knowledge_text, requirements)
    save_outputs(plan, knowledge_text)

    if args.interactive:
        interactive_loop(args.api_key, knowledge_text)


if __name__ == "__main__":
    main()

#D:/miniconda/envs/facemedia/python.exe multi_video_travel_agent_single_map_interactive.py --videos "try1.mp4" "try2.mp4" --days 3 --people 2 --budget 3000 --style "轻松型" --group "大人" --extra "喜欢拍照和美食，不想太累" --interactive