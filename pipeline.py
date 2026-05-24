# -*- coding: utf-8 -*-
"""
Douyin 分享链接 → 视频 → 转写 + 关键帧 + OCR + 元数据 → 结构化攻略（含 lat/lng/emoji/打分）
对外只暴露 run_pipeline / revise_plan / render_markdown 三个函数。
"""
import os
import re
import json
import hashlib
import logging
import shutil
import tempfile
import subprocess
from pathlib import Path
from typing import List, Dict, Optional, Callable

import requests

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai-next.com")
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
ASR_MODEL = "whisper-1"

SHARE_URL_RE = re.compile(r"https?://[^\s一-鿿]+")

# 视频解析缓存（按 文件路径 + size + mtime 的 MD5 作为 key），重复跑同一文件不会再 ASR/OCR
CACHE_DIR = Path(__file__).with_name("output") / "video_cache"

SCHEMA_HINT = """{
  "title": "上海2日游攻略",
  "city": "上海",
  "days": 2,
  "people": 2,
  "budget_per_day": 500,
  "budget_total": 1000,
  "travel_style": "轻松型",
  "target_group": "大人",
  "themes": ["人文古迹", "美食巡游"],
  "itinerary": [
    {
      "day": 1,
      "theme": "城市经典打卡",
      "stops": [
        {
          "place": "外滩",
          "lat": 31.2397,
          "lng": 121.4905,
          "emoji": "🌃",
          "type": "景点",
          "activities": ["看万国建筑群", "拍陆家嘴夜景"],
          "time_hours": 2,
          "cost": 0,
          "transport": "地铁2号线",
          "polarity": "must_go",
          "scores": {"value": 9, "photo": 10, "crowd": 7, "accessibility": 9},
          "reason": "经典城市天际线，傍晚最佳光线",
          "tip": "傍晚日落前后光线最佳",
          "source_hint": "视频开头提到的必拍点",
          "avoid": false
        }
      ]
    }
  ],
  "must_go": ["外滩日落", "南翔小笼"],
  "avoid": ["城隍庙小吃街", "节假日豫园"],
  "backup_list": [
    {"place": "M50 创意园", "reason": "顺路但与艺术兴趣不强，留作备选"}
  ],
  "summary": {
    "total_cost": 1000,
    "route_logic": "Day1 外滩-南京路-豫园 紧凑步行；Day2 浦东 + 田子坊 分区移动",
    "notes": "建议提前规划交通"
  }
}"""

SYSTEM_PROMPT = (
    "你是中文旅行规划 AI Agent。你会收到视频博主的 ASR 文本、OCR 文字、视频元数据，和用户的旅行约束。\n"
    "你的任务**不是把视频里所有地点都列出来**，而是把视频里提到的地点当作候选池，\n"
    "结合用户的天数、人数、预算、旅行强度、适合人群和兴趣偏好，筛出值得、顺路、可执行的路线。\n\n"
    "硬性规则：\n"
    "1. 视频中提到的地点不是都要去，必须筛选；不顺路、与偏好不符的放入 backup_list 而非 itinerary。\n"
    "2. 每天路线按区域聚类，减少折返和跨区域移动；每天 theme 字段写清当天主线。\n"
    "3. 轻松型每天 2-3 个 stops，特种兵型每天 4-5 个，老人/亲子降低体力消耗、增加休息点。\n"
    "4. 地点必须属于当前城市/区域。同名地点（如多个城市都有的连锁/景区）必须结合 city、OCR、ASR 上下文判断；\n"
    "   无法确认属于当前城市的，**禁止放进 itinerary**，应放进 backup_list 并说明原因。\n"
    "5. itinerary 不能为空，每个 day 至少 2 个、最多 5 个 stops。\n"
    "6. must_go 是推荐清单，真正路线必须写进 itinerary.stops；avoid 列出明确不推荐的点。\n\n"
    "【路线优化 · 重要】：\n"
    "A. 每一天的 stops 必须按地铁/公交线路顺序首尾相接，**严禁折返、严禁路线交叉**。\n"
    "B. 优先安排同一条地铁线 / 同一片步行可达区域的站点，把需要换乘 2 次以上的点放到不同天或 backup_list。\n"
    "C. 每天起点尽量是地铁/公交可达性强的大站，终点选靠近酒店或夜景观赏地。\n"
    "D. 同区域内多个点：按从北到南或从西到东等单向顺序排列，不要 A→B→C→回到A 附近。\n"
    "E. transport 字段要写**具体的地铁线号/公交线号**（如 \"地铁 1 号线 静安寺站\"、\"71 路公交\"、\"步行 8 分钟\"），\n"
    "   不能只写\"地铁\"\"打车\"这种含糊词。\n"
    "F. 跨天移动要在下一天首站的 transport 字段写清城际方式（如 \"上海高铁至苏州 30 分钟\"、\"地铁 17 号线 + 步行\"）。\n"
    "G. 输出 summary.route_logic 必须用一两句话说明每天怎么用地铁/公交串起来。\n\n"
    "【精确度 · 重要】：\n"
    "P1. **place 字段必须精确到具体景点入口 / 具体店铺 / 观景台 / 打卡角度**，"
    "    不能用行政区名 / 大概念。\n"
    "    × 反例：'外滩'、'南京路'、'夫子庙'、'西湖'\n"
    "    ✓ 正例：'外滩观景平台·陈毅广场'、'南京路·南翔馒头店总店'、'夫子庙·乌衣巷古井'、'西湖·断桥残雪观景点'\n"
    "P2. recommended_foods 必须给具体**店名 + 招牌菜**，不要只写'当地小吃'。\n"
    "    × 反例：'江南小吃'、'本地美食'\n"
    "    ✓ 正例：'松鹤楼·松鼠桂鱼'、'绿杨邨酒家·虾仁两面黄'、'王家沙·蟹粉小笼'\n"
    "P3. activities 是可执行动作 + 具体目标，不要笼统。\n"
    "    × 反例：'拍照'、'购物'、'吃东西'\n"
    "    ✓ 正例：'拍南翔小笼出锅的瞬间'、'在 IFC LV 旗舰店打卡'、'喝鸡头米羹（哑巴生煎隔壁）'\n"
    "P4. lat/lng 务必准确到具体景点入口的位置（不是行政区中心），并确认与 place 描述匹配。\n\n"
    "每个 stop 必须给出：\n"
    "  · lat / lng （**GCJ-02 火星坐标系**，即高德/腾讯地图的标准。"
    "    本系统使用高德地图瓦片，请勿输出 WGS-84 GPS 坐标，否则在中国地区会偏移 300-500 米）；\n"
    "  · emoji（如 🏯 🍜 🌃 🏞 🎢）；\n"
    "  · type（景点/餐饮/购物/交通/住宿/休闲）；\n"
    "  · activities（数组，2-4 个具体动作）；\n"
    "  · time_hours、cost、transport（具体到地铁线号/公交线号/步行时长）；\n"
    "  · polarity（must_go / normal / avoid）和 avoid (布尔)；\n"
    "  · scores 四维 0-10：value(值得) / photo(上镜) / crowd(人挤人,越低越拥挤) / accessibility(可达性)；\n"
    "  · reason（为什么把这个点安排在这一天这个时段，是否在同一条地铁线/同一区域）；\n"
    "  · tip（实用小建议）；\n"
    "  · source_hint（来自哪段视频线索，如\"视频中 03:20 处提到\"）。\n\n"
    "顶层必须给出：title、city、days、people、budget_per_day、budget_total、travel_style、target_group、\n"
    "itinerary、must_go(3-5)、avoid(3-5)、backup_list(0-5 候选未安排)、summary{total_cost, route_logic, notes}。\n\n"
    "只输出 JSON 本体，不要 markdown 代码块，不要任何解释文字。"
)

# 多模态版（视觉模型用）：在原 SYSTEM_PROMPT 基础上强化"看图"指令
SYSTEM_PROMPT_MULTIMODAL = (
    SYSTEM_PROMPT +
    "\n\n【视觉理解 · 你能看到关键帧画面】\n"
    "用户的消息里会同时附上**多张视频关键帧 image_url**。你必须真正去看每一张：\n"
    "1. 从画面里识别建筑外观、店铺招牌中英日韩文、路牌、地铁站名、菜单价格、出现的人流密度；\n"
    "2. 结合 ASR 转写时间轴大致判断哪一帧对应哪段话，把"
    "   博主真正去了的地方（露脸吃饭/进门/拿招牌道具）与一掠而过的镜头区分；\n"
    "3. 综合视觉 + 文字 推断地点的城市/区域，避免把同名地点错放进错的城市；\n"
    "4. 从画面识别季节（樱花/红叶/雪/绿叶）、天气、白天黑夜，反映到 tip 字段；\n"
    "5. 如果某个地点视频里看起来人爆挤、商业化重、广告浓厚 → 倾向放进 avoid 或调低 scores；\n"
    "6. 每个 stop 的 source_hint 必须写清楚是从第几张画面或哪段语音判断的，方便用户核对；\n"
    "7. **如果画面里清楚出现某地标但 ASR 没提**，仍要写进 itinerary；反之 ASR 提到但画面没出现的，"
    "   只放 backup_list 并说明。"
)


# -------------------- 视频解析缓存 --------------------
def _video_cache_key(video_path: Path) -> str:
    st = video_path.stat()
    raw = f"{video_path.resolve()}_{st.st_size}_{st.st_mtime}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def load_video_cache(video_path: Path) -> Optional[Dict]:
    if not video_path.exists():
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cp = CACHE_DIR / f"{_video_cache_key(video_path)}.json"
    if not cp.exists():
        return None
    try:
        return json.loads(cp.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("读取视频缓存失败：%s", e)
        return None


def save_video_cache(video_path: Path, data: Dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cp = CACHE_DIR / f"{_video_cache_key(video_path)}.json"
    try:
        cp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("视频解析缓存 → %s", cp.name)
    except Exception as e:
        logger.warning("写视频缓存失败：%s", e)


# -------------------- 工具 --------------------
def ensure_cmd(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _run(cmd: List[str]) -> None:
    logger.info("$ %s", " ".join(cmd))
    subprocess.run(cmd, check=True)


def extract_share_url(text: str) -> str:
    """从抖音分享文案中抽取真实 URL。"""
    if not text:
        raise ValueError("输入为空")
    m = SHARE_URL_RE.search(text)
    if not m:
        raise ValueError(f"未找到 URL：{text[:120]}")
    return m.group(0).rstrip(",.;。，")


# -------------------- 视频下载 / 抽帧 / 抽音频 --------------------
def _prime_douyin_cookies(work_dir: Path) -> Optional[Path]:
    """用 curl_cffi 访问 douyin 首页拿 ttwid/__ac_nonce 等 cookie，写成 Netscape 格式给 yt-dlp 用。"""
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        logger.info("curl_cffi 未安装，跳过 cookie 预热")
        return None
    try:
        sess = cffi_requests.Session(impersonate="chrome")
        sess.get("https://www.douyin.com/", timeout=15)
        sess.get("https://www.douyin.com/?recommend=1", timeout=15)
        cookies = sess.cookies
        cookie_path = work_dir / "douyin_cookies.txt"
        lines = ["# Netscape HTTP Cookie File\n"]
        for c in cookies.jar:
            secure = "TRUE" if c.secure else "FALSE"
            http_only = "FALSE"
            domain_flag = "TRUE" if (c.domain or "").startswith(".") else "FALSE"
            expires = int(c.expires) if c.expires else 0
            lines.append(
                f"{c.domain or '.douyin.com'}\t{domain_flag}\t{c.path or '/'}\t{secure}\t{expires}\t{c.name}\t{c.value}\n"
            )
        cookie_path.write_text("".join(lines), encoding="utf-8")
        logger.info("已写入 %d 条 douyin cookie → %s", len(cookies.jar), cookie_path)
        return cookie_path
    except Exception as e:
        logger.warning("douyin cookie 预热失败：%s", e)
        return None


def _resolve_douyin_short_url(url: str) -> str:
    """v.douyin.com/xxx/ 这种短链 → 真正的 www.douyin.com/video/<id> 长链。"""
    if "v.douyin.com" not in url:
        return url
    try:
        from curl_cffi import requests as cffi_requests
        r = cffi_requests.get(url, impersonate="chrome", allow_redirects=True, timeout=15)
        m = re.search(r"/(?:video|note)/(\d+)", r.url)
        if m:
            return f"https://www.douyin.com/video/{m.group(1)}"
    except Exception as e:
        logger.warning("短链解析失败：%s", e)
    return url


def download_video(url: str, work_dir: Path) -> Path:
    if not ensure_cmd("yt-dlp"):
        raise RuntimeError("缺少 yt-dlp，请运行：pip install yt-dlp")
    work_dir.mkdir(parents=True, exist_ok=True)
    out_tmpl = str(work_dir / "video.%(ext)s")

    # 抖音站点的特殊处理：解析短链 + 预热 cookie + Chrome 指纹
    is_douyin = "douyin.com" in url
    if is_douyin:
        url = _resolve_douyin_short_url(url)

    cmd: List[str] = ["yt-dlp", "-f", "mp4/best", "-o", out_tmpl]
    cookies_path: Optional[Path] = None
    if is_douyin:
        cookies_path = _prime_douyin_cookies(work_dir)
        if cookies_path:
            cmd += ["--cookies", str(cookies_path)]
        cmd += ["--impersonate", "chrome"]

    cmd.append(url)
    _run(cmd)
    cands = sorted(work_dir.glob("video.*"))
    if not cands:
        raise RuntimeError("视频下载失败")
    return cands[0]


def extract_audio(video_path: Path, work_dir: Path) -> Path:
    if not ensure_cmd("ffmpeg"):
        raise RuntimeError("缺少 ffmpeg，请安装 FFmpeg 并加入 PATH")
    audio_path = work_dir / "audio.wav"
    _run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(video_path), "-vn", "-ac", "1", "-ar", "16000",
        str(audio_path),
    ])
    return audio_path


def _probe_duration(video_path: Path) -> float:
    if not ensure_cmd("ffprobe"):
        return 0.0
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
            capture_output=True, text=True, check=True,
        )
        return float(r.stdout.strip() or 0.0)
    except Exception:
        return 0.0


def extract_keyframes(video_path: Path, work_dir: Path, n: int = 5) -> List[Path]:
    """等间隔抽 n 帧。"""
    frames_dir = work_dir / "frames"
    frames_dir.mkdir(exist_ok=True)
    duration = _probe_duration(video_path)
    paths: List[Path] = []

    if duration > 1:
        for i in range(n):
            t = duration * (i + 0.5) / n
            out = frames_dir / f"frame_{i:02d}.jpg"
            try:
                _run([
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-ss", f"{t:.2f}", "-i", str(video_path),
                    "-frames:v", "1", "-q:v", "3", str(out),
                ])
                if out.exists():
                    paths.append(out)
            except subprocess.CalledProcessError:
                continue
    else:
        # duration 未知时按 fps 抽
        interval = 1.2
        _run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(video_path), "-vf", f"fps=1/{interval}",
            str(frames_dir / "frame_%05d.jpg"),
        ])
        paths = sorted(frames_dir.glob("frame_*.jpg"))[:n]

    return paths


# -------------------- 元数据 --------------------
def get_metadata(url: str) -> Dict:
    try:
        import yt_dlp
    except ImportError:
        return {}
    try:
        with yt_dlp.YoutubeDL({"skip_download": True, "quiet": True, "no_warnings": True}) as ydl:
            ex = ydl.extract_info(url, download=False)
            return {
                "title": ex.get("title") or "",
                "description": ex.get("description") or "",
                "uploader": ex.get("uploader") or "",
                "tags": ex.get("tags") or [],
                "duration": ex.get("duration"),
            }
    except Exception as e:
        logger.warning("元数据获取失败：%s", e)
        return {}


# -------------------- 语音转写 --------------------
def transcribe(audio_path: Path, api_key: str, base_url: str = DEFAULT_BASE_URL) -> str:
    """先用兼容 OpenAI 的 Whisper API；失败/无 Key 时回退本地 faster-whisper。"""
    if api_key:
        try:
            url = base_url.rstrip("/") + "/v1/audio/transcriptions"
            with open(audio_path, "rb") as f:
                resp = requests.post(
                    url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    files={"file": (audio_path.name, f, "audio/wav")},
                    data={"model": ASR_MODEL, "language": "zh"},
                    timeout=180,
                    proxies={"http": None, "https": None},
                )
            if resp.status_code == 200:
                return (resp.json().get("text") or "").strip()
            logger.warning("Whisper API %d：%s", resp.status_code, resp.text[:200])
        except Exception as e:
            logger.warning("Whisper API 异常：%s", e)

    try:
        from faster_whisper import WhisperModel
        logger.info("使用本地 faster-whisper small")
        model = WhisperModel("small", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(str(audio_path), language="zh", beam_size=5)
        return "".join(s.text for s in segments).strip()
    except ImportError:
        logger.warning("faster-whisper 未安装")
    except Exception as e:
        logger.warning("本地 ASR 失败：%s", e)
    return ""


# -------------------- 关键帧 OCR --------------------
def ocr_frames(frame_paths: List[Path]) -> List[str]:
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        logger.info("rapidocr_onnxruntime 未安装，跳过 OCR")
        return []
    ocr = RapidOCR()
    lines: List[str] = []
    for p in frame_paths:
        try:
            result, _ = ocr(str(p))
            if not result:
                continue
            for _, txt, conf in result:
                if conf >= 0.5 and len(txt) >= 2:
                    lines.append(txt.strip())
        except Exception as e:
            logger.warning("OCR %s 失败：%s", p.name, e)
    seen, out = set(), []
    for t in lines:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


# -------------------- 文本融合 + LLM 调用 --------------------
def fuse_text(transcript: str, ocr_lines: List[str], meta: Dict) -> str:
    parts: List[str] = []
    if meta.get("title"):
        parts.append(f"标题：{meta['title']}")
    if meta.get("description"):
        parts.append(f"描述：{meta['description']}")
    if meta.get("tags"):
        parts.append("标签：" + ", ".join(str(x) for x in meta["tags"]))
    if transcript:
        parts.append("语音转写：" + transcript)
    if ocr_lines:
        parts.append("画面文字：" + "；".join(ocr_lines))
    return "\n".join(parts)


def _strip_fence(content: str) -> str:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"```\s*$", "", content)
    return content.strip()


# -------------------- 路线优化（贪心最近邻） --------------------
def _haversine(lat1, lng1, lat2, lng2) -> float:
    """两点距离（公里），小区域可当作平面距离够用。"""
    import math
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlng/2)**2)
    return 2 * R * math.asin(math.sqrt(a))


def optimize_routes(plan: Dict) -> Dict:
    """
    就地修改 plan：每天的 stops 用最近邻贪心重排，让相邻站点尽量接近。
    保留首站（通常是博主推荐起点 / 必去 / 跨天衔接点）作为锚点。
    """
    days = plan.get("itinerary") or []
    for day in days:
        stops = day.get("stops") or []
        if len(stops) < 3:
            continue
        # 先确认所有 stop 都有坐标
        coords_ok = []
        no_coord  = []
        for s in stops:
            try:
                lat = float(s.get("lat")); lng = float(s.get("lng"))
                coords_ok.append((lat, lng, s))
            except (TypeError, ValueError):
                no_coord.append(s)
        if len(coords_ok) < 3:
            continue

        # 锚点：保留 LLM 给出的首站（通常是博主推荐的起点）
        anchor_lat, anchor_lng, anchor_stop = coords_ok[0]
        remaining = coords_ok[1:]
        ordered = [anchor_stop]
        cur_lat, cur_lng = anchor_lat, anchor_lng

        # 最近邻贪心：每次取距离当前点最近的下一站
        while remaining:
            remaining.sort(key=lambda x: _haversine(cur_lat, cur_lng, x[0], x[1]))
            nxt_lat, nxt_lng, nxt_stop = remaining.pop(0)
            ordered.append(nxt_stop)
            cur_lat, cur_lng = nxt_lat, nxt_lng

        day["stops"] = ordered + no_coord
    return plan


def call_llm(api_key: str, fused: str, days: int, budget: float,
             base_url: str = DEFAULT_BASE_URL, model: str = DEFAULT_MODEL,
             people: int = 2, travel_style: str = "轻松型",
             target_group: str = "大人", extra: str = "",
             themes: Optional[List[str]] = None,
             frames: Optional[List[Path]] = None) -> Dict:
    """
    生成结构化攻略。当 frames 不为空且 model 是视觉模型时，自动启用多模态调用：
    把关键帧作为 image_url 一起塞给 LLM，让模型真正"看"视频画面。
    视觉调用失败会自动回退到纯文本模式。
    """
    themes = themes or []
    themes_line = f"主题偏好：{', '.join(themes)}\n" if themes else ""
    requirements = (
        f"天数：{days}\n"
        f"人数：{people}\n"
        f"每天预算：{budget} 元（总预算约 {budget * max(days,1):.0f} 元）\n"
        f"旅行强度：{travel_style}\n"
        f"适合人群：{target_group}\n"
        f"{themes_line}"
        f"额外要求：{extra or '无'}\n"
    )

    # ---------- 优先尝试视觉模型 ----------
    if frames and _is_vision_model(model):
        try:
            plan = _call_llm_multimodal(
                api_key, fused, frames, requirements, base_url, model)
            logger.info("✓ 多模态调用成功（%d 张关键帧 + ASR + OCR）", len(frames))
            return validate_plan(plan)
        except Exception as e:
            logger.warning("多模态调用失败，回退纯文本：%s", e)

    # ---------- 纯文本模式 ----------
    return validate_plan(_call_llm_text(api_key, fused, requirements, base_url, model))


# ============================================================
#  视觉模型识别 + 多模态调用 + 纯文本调用
# ============================================================
def _is_vision_model(model: str) -> bool:
    """模型名包含这些关键字 → 认为支持视觉。覆盖 OpenAI/Claude/Gemini/Qwen 主流。"""
    m = (model or "").lower()
    keywords = ("4o", "4-o", "vision", "claude-3", "claude-4", "sonnet",
                "haiku", "opus", "gemini", "qwen-vl", "qwen2-vl", "qwen2.5-vl",
                "glm-4v", "internvl", "minicpm-v", "yi-vl", "llava")
    return any(k in m for k in keywords)


def _encode_frame_b64(path: Path, max_side: int = 1024) -> str:
    """读取一张关键帧 → 缩放 → base64 编码。"""
    import base64
    data = None
    try:
        # 优先用 Pillow 压缩，避免 1MB+ 的大图把请求撑爆
        from PIL import Image
        import io
        with Image.open(str(path)) as im:
            im = im.convert("RGB")
            w, h = im.size
            scale = max_side / max(w, h)
            if scale < 1:
                im = im.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=80)
            data = buf.getvalue()
    except Exception:
        # 没装 Pillow → 直接发原图
        data = Path(path).read_bytes()
    return base64.b64encode(data).decode("ascii")


def _call_llm_multimodal(api_key: str, fused: str, frames: List[Path],
                          requirements: str, base_url: str, model: str) -> Dict:
    """带视觉的 LLM 调用：text + N 张关键帧 image_url。"""
    url = base_url.rstrip("/") + "/v1/chat/completions"

    # 最多塞 8 张帧，避免请求过大
    use_frames = [p for p in (frames or []) if Path(p).exists()][:8]
    image_blocks = []
    for fp in use_frames:
        try:
            b64 = _encode_frame_b64(fp, max_side=1024)
            image_blocks.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            })
        except Exception as e:
            logger.warning("encode frame %s 失败：%s", fp, e)

    if not image_blocks:
        raise RuntimeError("没有可用关键帧")

    text_part = (
        f"以下是抖音/B站旅行视频的多模态资料：\n\n"
        f"【ASR 语音转写 + OCR 画面文字 + 视频元数据】\n{fused}\n\n"
        f"【关键帧】（按时间顺序，共 {len(image_blocks)} 张，请仔细看每一张）\n"
    )
    constraints_part = (
        f"\n\n【用户当前约束与偏好】\n{requirements}\n"
        f"请你**结合上面的画面和文字**，识别博主真正去过的地点、招牌名字、景点类型、季节、人流密度，"
        f"按下面结构生成最终旅行方案 JSON：\n{SCHEMA_HINT}\n\n"
        f"⚠️ 关键要求：每个 stop 的 source_hint 字段要写清你是从**哪张关键帧**或哪段转写认出来的，"
        f"如果画面里能识别出建筑/招牌/字幕，请在 reason 里说明，让结果可追溯。"
    )

    user_content = (
        [{"type": "text", "text": text_part}]
        + image_blocks
        + [{"type": "text", "text": constraints_part}]
    )

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_MULTIMODAL},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.25,
        "response_format": {"type": "json_object"},
    }
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json"},
        json=body, timeout=300,
        proxies={"http": None, "https": None},
    )
    if resp.status_code != 200 and "response_format" in resp.text:
        body.pop("response_format", None)
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            json=body, timeout=300,
            proxies={"http": None, "https": None},
        )
    if resp.status_code != 200:
        raise RuntimeError(f"vision LLM {resp.status_code}：{resp.text[:300]}")
    content = _strip_fence(resp.json()["choices"][0]["message"]["content"])
    return json.loads(content)


def _call_llm_text(api_key: str, fused: str, requirements: str,
                    base_url: str, model: str) -> Dict:
    """纯文本模式（兼容所有 Chat Completions 接口）"""
    url = base_url.rstrip("/") + "/v1/chat/completions"
    user_content = (
        f"【视频信息】\n{fused}\n\n"
        f"【用户当前约束与偏好】\n{requirements}\n"
        f"请基于以上信息按下面结构生成最终旅行方案 JSON：\n{SCHEMA_HINT}"
    )
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=body, timeout=180,
        proxies={"http": None, "https": None},
    )
    if resp.status_code != 200 and "response_format" in resp.text:
        body.pop("response_format", None)
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body, timeout=180,
            proxies={"http": None, "https": None},
        )
    if resp.status_code != 200:
        raise RuntimeError(f"LLM 调用失败 {resp.status_code}：{resp.text[:500]}")
    content = _strip_fence(resp.json()["choices"][0]["message"]["content"])
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"模型返回非合法 JSON：{e}\n原文片段：{content[:500]}")


def validate_plan(plan: Dict) -> Dict:
    """硬校验 + 补默认值。"""
    itinerary = plan.get("itinerary") or []
    if not itinerary:
        raise RuntimeError("模型返回的 itinerary 为空，无法生成地图")
    for day in itinerary:
        if not day.get("stops"):
            raise RuntimeError(f"第 {day.get('day')} 天 stops 为空，无法生成地图")
        for s in day["stops"]:
            s.setdefault("type", "景点")
            s.setdefault("activities", [])
            s.setdefault("transport", "")
            s.setdefault("polarity", "normal")
            s.setdefault("avoid", s.get("polarity") == "avoid")
            s.setdefault("reason", "")
            s.setdefault("source_hint", "")
            s.setdefault("tip", "")
            s.setdefault("scores", {})
            s.setdefault("emoji", "📍")
    plan.setdefault("must_go", [])
    plan.setdefault("avoid", [])
    plan.setdefault("backup_list", [])
    plan.setdefault("summary", {})
    return plan


def revise_plan(api_key: str, plan: Dict, instruction: str,
                base_url: str = DEFAULT_BASE_URL, model: str = DEFAULT_MODEL) -> Dict:
    """单轮对话式改路线。"""
    url = base_url.rstrip("/") + "/v1/chat/completions"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT +
             "\n你将收到一份已存在的攻略 JSON 与用户的修改诉求，请输出修改后的完整 JSON（保持字段结构不变，"
             "包括 type/transport/reason/source_hint/backup_list 等所有字段，未涉及修改的 stop 保留原内容）。\n"
             "【必去 / 避雷格式】must_go、avoid、avoid_list 可能是字符串数组也可能是 "
             "`[{place, reason}]` 对象数组——必须保留原数据的形式，不要把对象数组改写成字符串数组，"
             "也不要反向改写。若新增项，请沿用同一种形式。"},
            {"role": "user", "content":
             f"现有攻略：\n{json.dumps(plan, ensure_ascii=False)}\n\n用户要求：{instruction}\n\n"
             f"请只输出修改后的完整 JSON。"},
        ],
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
    }
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=body, timeout=180,
        proxies={"http": None, "https": None},
    )
    if resp.status_code != 200 and "response_format" in resp.text:
        body.pop("response_format", None)
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body, timeout=180,
            proxies={"http": None, "https": None},
        )
    if resp.status_code != 200:
        raise RuntimeError(f"修改失败：{resp.text[:500]}")
    content = _strip_fence(resp.json()["choices"][0]["message"]["content"])
    return validate_plan(json.loads(content))


# -------------------- Markdown 渲染 --------------------
def render_markdown(plan: Dict) -> str:
    lines: List[str] = [f"# {plan.get('title', '旅行攻略')}"]
    if plan.get("city"):
        lines.append(f"- 城市：{plan['city']}")
    lines.append(f"- 天数：{plan.get('days', '')} 天")
    if plan.get("people"):
        lines.append(f"- 人数：{plan['people']}")
    lines.append(f"- 预算：约 ¥{plan.get('budget_per_day', '')}/天"
                 + (f"（总 ¥{plan['budget_total']}）" if plan.get('budget_total') else ""))
    if plan.get("travel_style"):
        lines.append(f"- 强度：{plan['travel_style']}")
    if plan.get("target_group"):
        lines.append(f"- 适合人群：{plan['target_group']}")
    lines.append("")

    for day in plan.get("itinerary", []):
        head = f"## 第{day.get('day', '')}天"
        if day.get("theme"):
            head += f" · {day['theme']}"
        lines.append(head)
        for s in day.get("stops", []):
            emoji = s.get("emoji", "📍")
            place = s.get("place", "")
            stype = s.get("type", "")
            activities = "、".join(s.get("activities", []))
            t = s.get("time_hours", "")
            c = s.get("cost", "")
            transport = s.get("transport", "")
            tip = s.get("tip", "")
            reason = s.get("reason", "")
            source_hint = s.get("source_hint", "")
            pol = s.get("polarity", "")
            pol_mark = {"must_go": " ⭐必去", "avoid": " ⚠️避雷"}.get(pol, "")
            scores = s.get("scores") or {}
            score_str = ""
            if scores:
                score_str = (f"  `值得 {scores.get('value','-')}/上镜 {scores.get('photo','-')}/"
                             f"人挤人 {scores.get('crowd','-')}/可达 {scores.get('accessibility','-')}`")
            lines.append(f"- {emoji} **{place}**{pol_mark}"
                         + (f"｜{stype}" if stype else "")
                         + f"｜{t}小时｜约¥{c}"
                         + (f"｜🚇 {transport}" if transport else "")
                         + f"{score_str}")
            if activities:
                lines.append(f"  - 🎯 活动：{activities}")
            if reason:
                lines.append(f"  - 🧭 安排理由：{reason}")
            if tip:
                lines.append(f"  - 💡 Tips：{tip}")
            if source_hint:
                lines.append(f"  - 🎬 视频线索：{source_hint}")
        lines.append("")

    def _fmt_duo(x):
        if isinstance(x, dict):
            place = x.get("place") or x.get("name") or ""
            reason = x.get("reason") or x.get("note") or ""
            return f"**{place}** — {reason}" if (place and reason) else (place or reason or "")
        return str(x)

    if plan.get("must_go"):
        lines.append("## ⭐ 必去清单")
        for x in plan["must_go"]:
            lines.append(f"- {_fmt_duo(x)}")
        lines.append("")

    if plan.get("avoid") or plan.get("avoid_list"):
        lines.append("## ⚠️ 避雷清单")
        for x in (plan.get("avoid") or plan.get("avoid_list") or []):
            lines.append(f"- {_fmt_duo(x)}")
        lines.append("")

    if plan.get("backup_list"):
        lines.append("## 🗂 候选但未安排")
        for item in plan["backup_list"]:
            if isinstance(item, dict):
                lines.append(f"- **{item.get('place','')}** — {item.get('reason','')}")
            else:
                lines.append(f"- {item}")
        lines.append("")

    summary = plan.get("summary") or {}
    lines.append("---")
    if summary.get("total_cost") is not None:
        lines.append(f"**总预算估算**：¥{summary['total_cost']}")
    if summary.get("route_logic"):
        lines.append(f"**路线逻辑**：{summary['route_logic']}")
    if summary.get("notes"):
        lines.append(summary["notes"])
    return "\n".join(lines)


# -------------------- 端到端管线 --------------------
def run_pipeline(
    url_or_share_text: str,
    api_key: str,
    days: int = 2,
    budget: float = 500,
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_MODEL,
    n_frames: int = 5,
    output_dir: Optional[Path] = None,
    progress: Optional[Callable[[str], None]] = None,
    local_video: Optional[str] = None,
    local_videos: Optional[List[str]] = None,
    people: int = 2,
    travel_style: str = "轻松型",
    target_group: str = "大人",
    extra: str = "",
    themes: Optional[List[str]] = None,
) -> Dict:
    """
    多模态视频解析 → 攻略生成。
    - local_videos（推荐）：1-5 个本地视频路径，走 new_logic_agent 多视频融合
    - local_video（旧）：单个本地视频路径，兼容旧调用
    - url_or_share_text：抖音分享文案（用 yt-dlp 下载）
    """
    def step(msg: str):
        logger.info(msg)
        if progress:
            progress(msg)

    # 优先使用 local_videos
    if local_videos:
        video_paths = [Path(v).expanduser().resolve() for v in local_videos][:5]
    elif local_video:
        video_paths = [Path(local_video).expanduser().resolve()]
    else:
        video_paths = []

    # 有本地视频 → 走新版多视频 agent
    if video_paths:
        return _run_pipeline_multi_video(
            video_paths, api_key,
            days=days, budget=budget, n_frames=n_frames,
            output_dir=output_dir, progress=progress,
            people=people, travel_style=travel_style,
            target_group=target_group, extra=extra, themes=themes,
            base_url=base_url, model=model,
        )

    # 无本地视频 → 走旧版下载流程（yt-dlp）
    return _run_pipeline_legacy(
        url_or_share_text, api_key,
        days=days, budget=budget, base_url=base_url, model=model,
        n_frames=n_frames, output_dir=output_dir, progress=progress,
        people=people, travel_style=travel_style,
        target_group=target_group, extra=extra, themes=themes,
    )


def _run_pipeline_multi_video(
    video_paths: List[Path], api_key: str,
    days: int, budget: float, n_frames: int,
    output_dir: Optional[Path], progress: Optional[Callable[[str], None]],
    people: int, travel_style: str, target_group: str,
    extra: str, themes: Optional[List[str]],
    base_url: str = "", model: str = "",
) -> Dict:
    """新版：多个本地视频 → analyze_one_video × N → 融合 → LLM → 路线"""
    def step(msg: str):
        logger.info(msg)
        if progress:
            progress(msg)

    from new_logic_agent import (
        analyze_one_video, build_all_fused_text, make_requirements,
        call_llm as new_call_llm, make_single_route_map,
    )

    out_dir = output_dir or Path(__file__).with_name("output")
    out_dir.mkdir(exist_ok=True)

    # 取消信号：progress 回调里抛 JobCancelled，传给 analyze_one_video
    # 让并行 worker 在每个子步骤前能及早响应
    def _check_cancel():
        if progress:
            # 调用 server 的 cb()：它会先过 control.check()，被取消时抛 JobCancelled
            # 这里不打印新消息，只是过一遍闸；用空串无意义，所以直接调用 progress("__check__")
            # 但 server 端会把消息塞进 logs。改用一个轻量协议：传 None 表示只 check。
            try:
                progress("")  # 空字符串表示心跳；server 端 cb 会跑 control.check()
            except Exception:
                raise

    # 并行视频解析：默认 2 路（可用 VIDEO_PARALLEL 环境变量调）。
    # 单个视频内部 Whisper / OCR 各有锁串行，跨视频时 ffmpeg / 帧抽取能真正并行。
    n_videos = len(video_paths)
    max_workers = max(1, min(n_videos, int(os.getenv("VIDEO_PARALLEL", "2"))))

    videos_data: List[Optional[Dict]] = [None] * n_videos
    transcripts: List[str] = [""] * n_videos

    for idx, video in enumerate(video_paths, start=1):
        if not video.exists():
            raise RuntimeError(f"本地视频不存在：{video}")

    if max_workers == 1:
        for idx, video in enumerate(video_paths, start=1):
            step(f"[{idx}/{n_videos}] 解析视频：{video.name}")
            data = analyze_one_video(
                video,
                every_seconds=2.0,
                max_frames=max(1, int(n_frames)),
                check_cancel=_check_cancel,
            )
            videos_data[idx - 1] = data
            transcripts[idx - 1] = (
                f"========== 视频 {idx}：{video.name} ==========\n"
                + (data.get("transcript", "") or "")
            )
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        step(f"并行解析 {n_videos} 个视频（并发 {max_workers}）…")
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            fut_to_idx = {
                ex.submit(
                    analyze_one_video, video,
                    2.0, max(1, int(n_frames)), _check_cancel
                ): (idx, video)
                for idx, video in enumerate(video_paths, start=1)
            }
            done_count = 0
            for fut in as_completed(fut_to_idx):
                idx, video = fut_to_idx[fut]
                try:
                    data = fut.result()
                except Exception as e:
                    # 让上层（server worker）捕获；其他 future 在退出 with 时被忽略
                    raise
                videos_data[idx - 1] = data
                transcripts[idx - 1] = (
                    f"========== 视频 {idx}：{video.name} ==========\n"
                    + (data.get("transcript", "") or "")
                )
                done_count += 1
                step(f"[{done_count}/{n_videos}] 完成：{video.name}")

    transcript = "\n\n".join(transcripts)
    fused = build_all_fused_text(videos_data)
    if not fused.strip():
        raise RuntimeError("未抽取到任何文本，无法生成攻略")

    (out_dir / "transcript.txt").write_text(transcript, encoding="utf-8")
    (out_dir / "fused.txt").write_text(fused, encoding="utf-8")

    step("生成结构化攻略（多视频融合）…")
    requirements = make_requirements(
        days=days, people=people, budget=budget,
        style=travel_style, group=target_group,
        extra=extra or ("主题偏好：" + "、".join(themes or []) if themes else ""),
    )
    plan = new_call_llm(api_key, fused, requirements)

    step("生成坐标 + 路线优化…")
    route_map_path = out_dir / "route_map_from_new_logic.html"
    points = make_single_route_map(plan, route_map_path,
                                   api_key=api_key,
                                   base_url=base_url or DEFAULT_BASE_URL,
                                   model=model or DEFAULT_MODEL)

    # 把 new_logic_agent 返回的坐标回填到 plan.itinerary.stops 上
    plan = _attach_new_points_to_plan(plan, points)

    # 跑一遍贪心最近邻避免折返
    plan = optimize_routes(plan)

    # 写入 UI 用的标准文件
    (out_dir / "guide.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "guide.md").write_text(render_markdown(plan), encoding="utf-8")
    (out_dir / "geocoded_points.json").write_text(
        json.dumps(points, ensure_ascii=False, indent=2), encoding="utf-8")

    # 渲染地图（用我们自己的 visualize，享用 OSRM 路网 + AMap 等）
    from visualize import render_map
    (out_dir / "map.html").write_text(render_map(plan, []), encoding="utf-8")

    step(f"✅ 完成（{len(video_paths)} 段视频融合）")
    return {
        "plan": plan,
        "transcript": transcript,
        "fused": fused,
        "frames": [],
        "points": points,
        "out_dir": out_dir,
    }


def _attach_new_points_to_plan(plan: Dict, points: List[Dict]) -> Dict:
    """把 new_logic_agent 返回的 geocoded points 回填到 plan.itinerary[*].stops[*]"""
    if not points:
        return plan
    by_key = {}
    for p in points:
        key = (p.get("day"), str(p.get("place") or "").strip())
        by_key[key] = p
    for day in plan.get("itinerary", []) or []:
        d = day.get("day")
        for stop in day.get("stops", []) or []:
            key = (d, str(stop.get("place") or "").strip())
            if key in by_key:
                pt = by_key[key]
                if pt.get("lat") is not None:
                    stop["lat"] = pt["lat"]
                if pt.get("lng") is not None:
                    stop["lng"] = pt["lng"]
                if pt.get("address") and not stop.get("address"):
                    stop["address"] = pt["address"]
    return plan


def _run_pipeline_legacy(
    url_or_share_text: str, api_key: str,
    days: int, budget: float, base_url: str, model: str,
    n_frames: int, output_dir: Optional[Path],
    progress: Optional[Callable[[str], None]],
    people: int, travel_style: str, target_group: str,
    extra: str, themes: Optional[List[str]],
) -> Dict:
    """旧版：通过 yt-dlp 下载视频 → 完整流水线（保留以兼容老调用）"""
    def step(msg: str):
        logger.info(msg)
        if progress:
            progress(msg)

    work = Path(tempfile.mkdtemp(prefix="douyin_pipe_"))
    out_dir = output_dir or Path(__file__).with_name("output")
    out_dir.mkdir(exist_ok=True)

    # 解析 URL（local_video 模式下也尽量解析，用于元数据）
    url = ""
    try:
        url = extract_share_url(url_or_share_text) if url_or_share_text else ""
    except Exception:
        url = ""

    try:
        if local_video:
            lv = Path(local_video).expanduser().resolve()
            if not lv.exists():
                raise RuntimeError(f"本地视频不存在：{lv}")
            video = lv
            step(f"使用本地视频：{lv.name}")
        else:
            if not url:
                raise RuntimeError("既无本地视频，也未识别到 URL")
            step("下载视频…")
            video = download_video(url, work)

        # 视频解析缓存：transcript / ocr_lines / frames（按 size+mtime 的 MD5 命中）
        cached = load_video_cache(video)
        cached_frames: List[Path] = []
        if cached:
            step(f"命中视频缓存（{video.name}），跳过 ASR / OCR")
            transcript = cached.get("transcript", "") or ""
            ocr_lines = cached.get("ocr_lines", []) or []
            cached_frames = [Path(p) for p in cached.get("frame_paths", []) if Path(p).exists()]

        if not cached:
            step("提取音频…")
            audio = extract_audio(video, work)

            step("语音转写…")
            transcript = transcribe(audio, api_key, base_url)

            step("抽取关键帧…")
            frames = extract_keyframes(video, work, n=n_frames)

            step("识别画面文字（OCR）…")
            ocr_lines = ocr_frames(frames)
        else:
            frames = cached_frames

        step("读取视频元数据…")
        meta = get_metadata(url) if url else {}

        fused = fuse_text(transcript, ocr_lines, meta)
        if not fused.strip():
            raise RuntimeError("未抽取到任何文本（转写、OCR、元数据全空）")

        step("生成结构化攻略…")
        plan = call_llm(api_key, fused, days, budget, base_url, model,
                        people=people, travel_style=travel_style,
                        target_group=target_group, extra=extra,
                        themes=themes,
                        frames=frames)  # 关键帧用于多模态视觉理解

        # 路线确定性优化：贪心最近邻，避免每天行程交叉
        step("路线优化（最近邻排序）…")
        plan = optimize_routes(plan)

        # 关键帧拷到 output/frames 便于嵌入
        out_frames_dir = out_dir / "frames"
        out_frames_dir.mkdir(exist_ok=True)
        # 先清空旧帧
        for old in out_frames_dir.glob("frame_*.jpg"):
            try:
                old.unlink()
            except Exception:
                pass
        out_frames: List[Path] = []
        for fr in frames:
            if not Path(fr).exists():
                continue
            dest = out_frames_dir / Path(fr).name
            shutil.copy(fr, dest)
            out_frames.append(dest)

        # 写入视频缓存（用 output/frames 下的稳定路径，下次命中后还能复用）
        if not cached:
            save_video_cache(video, {
                "filename": video.name,
                "transcript": transcript,
                "ocr_lines": ocr_lines,
                "frame_paths": [str(p) for p in out_frames],
            })

        # 落盘
        (out_dir / "guide.json").write_text(
            json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        (out_dir / "guide.md").write_text(render_markdown(plan), encoding="utf-8")
        (out_dir / "transcript.txt").write_text(transcript or "", encoding="utf-8")
        (out_dir / "fused.txt").write_text(fused, encoding="utf-8")

        # 地图
        from visualize import render_map
        map_html = render_map(plan, out_frames)
        (out_dir / "map.html").write_text(map_html, encoding="utf-8")

        step("✅ 全部完成")
        return {
            "plan": plan,
            "transcript": transcript,
            "ocr_lines": ocr_lines,
            "meta": meta,
            "frames": out_frames,
            "fused": fused,
            "url": url,
            "out_dir": out_dir,
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)
