# -*- coding: utf-8 -*-
"""
Flask 交互界面：
- 左侧：按天的攻略列表（点击定位到地图标记）
- 中间：folium 地图（iframe）
- 右侧：操作面板（加载 JSON / 粘贴抖音链接生成 / 一句话修改 / 地理编码补全）

启动：
    .venv/Scripts/python.exe server.py
    # 浏览器打开 http://127.0.0.1:5000
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Dict, List, Optional

import requests

# 把 venv 的 Scripts/ 目录加进 PATH，让 pipeline.py 里 shutil.which("yt-dlp") 能找到
_venv_scripts = Path(sys.executable).parent
os.environ["PATH"] = str(_venv_scripts) + os.pathsep + os.environ.get("PATH", "")

# 注入 imageio-ffmpeg 自带的 ffmpeg 二进制到 PATH（首次会从 imageio CDN 下载约 30MB）
def _ensure_ffmpeg_on_path() -> None:
    import shutil as _sh
    if _sh.which("ffmpeg"):
        return
    try:
        import imageio_ffmpeg
        src = Path(imageio_ffmpeg.get_ffmpeg_exe())
        if not src.exists():
            return
        dst = _venv_scripts / "ffmpeg.exe"
        if not dst.exists():
            _sh.copy2(src, dst)
        logging.info("ffmpeg → %s", dst)
    except Exception as e:
        logging.warning("imageio-ffmpeg 不可用：%s（请确保系统 PATH 中有 ffmpeg）", e)

_ensure_ffmpeg_on_path()

from flask import Flask, jsonify, render_template, request, send_from_directory

import geocode
import post_trip
import travel_memory
from visualize import render_map

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR / "output"
OUT_DIR.mkdir(exist_ok=True)

app = Flask(__name__, template_folder=str(BASE_DIR / "templates"),
            static_folder=str(BASE_DIR / "static"))

class JobCancelled(Exception):
    """协作式取消：worker 在下次 progress 回调时抛出。"""
    pass


class JobControl:
    """单任务控制器：pause/resume/cancel。

    - pause_event: set = 运行，clear = 暂停（worker 在 progress 回调中 wait）
    - cancel_event: set = 已请求取消
    """
    def __init__(self):
        self.pause_event = threading.Event()
        self.pause_event.set()
        self.cancel_event = threading.Event()
        self.thread: Optional[threading.Thread] = None

    def check(self):
        # 暂停时阻塞；继续后若已被取消则抛出
        self.pause_event.wait()
        if self.cancel_event.is_set():
            raise JobCancelled()

    @property
    def paused(self) -> bool:
        return not self.pause_event.is_set()


# 全局状态（单用户场景）
STATE: Dict = {
    "plan": None,        # 当前攻略 dict
    "frames": [],        # 关键帧路径
    "job": None,         # {"status": "running|paused|done|error|cancelled", "step": str, "logs": [...], "error": str}
    "control": None,     # JobControl 实例（仅当前任务）
    "lock": threading.Lock(),
}


def _job_is_active() -> bool:
    """当前是否真有任务在跑——线程仍然存活才算。"""
    job = STATE.get("job")
    ctl: Optional[JobControl] = STATE.get("control")
    if not job or job.get("status") not in ("running", "paused"):
        return False
    t = ctl.thread if ctl else None
    if t is None or not t.is_alive():
        # 状态残留：worker 已死但状态没刷回来 → 视为可以重新提交
        return False
    return True


MAX_UPLOAD_FILES = 5


def _as_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "是", "开"}


def _selected_memory_ids(body: Dict):
    """None means legacy all-memory retrieval; [] means user selected nothing."""
    if "selected_memory_ids" in body:
        raw = body.get("selected_memory_ids") or []
    elif "memory_ids" in body:
        raw = body.get("memory_ids") or []
    else:
        return None
    if isinstance(raw, str):
        return [x.strip() for x in raw.split(",") if x.strip()]
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    return []


def _read_output_text(name: str, *, max_chars: int = 5000) -> str:
    path = OUT_DIR / name
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:max_chars]
    except Exception:
        return ""


def _record_from_post_trip_body(body: Dict, plan: Optional[Dict]) -> Optional[Dict]:
    record_id = (body.get("record_id") or "").strip()
    if record_id:
        return post_trip.get_record(record_id)
    raw = body.get("record") if isinstance(body.get("record"), dict) else body
    if not isinstance(raw, dict):
        return None
    record = post_trip.normalize_record(raw, plan=plan)
    if (
        not record.get("review_text")
        and not record.get("actual_places")
        and not record.get("skipped_places")
        and not record.get("added_places")
        and not record.get("photos")
    ):
        return post_trip.latest_record()
    return record


def _llm_text(api_key: str, *, base_url: str, model: str, system: str, user: str) -> str:
    url = base_url.rstrip("/") + "/v1/chat/completions"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.35,
        },
        timeout=120,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"LLM 请求失败 {resp.status_code}: {resp.text[:400]}")
    data = resp.json()
    return (data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()


def _memory_query_from_generate(body: Dict, *, share: str, themes: List[str]) -> Dict:
    return {
        "destination": body.get("destination") or body.get("city") or "",
        "city": body.get("city") or "",
        "days": body.get("days"),
        "people": body.get("people"),
        "budget": body.get("budget"),
        "travel_style": body.get("travel_style") or "",
        "target_group": body.get("target_group") or "",
        "themes": themes,
        "extra": body.get("extra") or "",
        "share_text": share or "",
    }


def _memory_query_from_revise(plan: Dict, instruction: str) -> Dict:
    return {
        "destination": plan.get("city") or "",
        "city": plan.get("city") or "",
        "days": plan.get("days"),
        "people": plan.get("people"),
        "budget": plan.get("budget_total") or plan.get("budget_per_day"),
        "travel_style": plan.get("travel_style") or "",
        "target_group": plan.get("target_group") or "",
        "themes": plan.get("themes") or [],
        "extra": instruction,
    }


def _inject_memory_text(text: str, context: str) -> str:
    if not context:
        return text
    base = text or ""
    return (
        f"{base}\n\n【个人旅行记忆】\n{context}\n"
        "请把这些记忆作为偏好证据：优先继承长期偏好，但如果本次用户要求不同，以本次要求为准。"
    ).strip()


# -------------------- 视频贡献值估算 --------------------
def _extract_video_sections(fused: str):
    """从 output/fused.txt 解析"视频 N"分段。"""
    import re as _re
    fused = fused or ""
    if not fused.strip():
        return []
    parts = _re.split(r"^\s*=+\s*视频\s*(\d+)\s*=+\s*$", fused, flags=_re.M)
    sections = []
    if len(parts) >= 3:
        for i in range(1, len(parts), 2):
            idx = parts[i]
            text = parts[i + 1] if i + 1 < len(parts) else ""
            m = _re.search(r"【视频文件】\s*\n\s*([^\n\r]+)", text)
            filename = (m.group(1).strip() if m else f"视频 {idx}")
            sections.append({"index": int(idx), "filename": filename, "text": text})
    else:
        m = _re.search(r"【视频文件】\s*\n\s*([^\n\r]+)", fused)
        sections.append({"index": 1, "filename": (m.group(1).strip() if m else "当前视频"), "text": fused})
    return sections


def _collect_plan_places(plan: Dict):
    places = []
    for day in plan.get("itinerary", []) or []:
        for st in day.get("stops", []) or []:
            name = str(st.get("place") or "").strip()
            if name and name not in places:
                places.append(name)
    for key in ("must_go", "avoid", "avoid_list", "backup_list"):
        for item in plan.get(key, []) or []:
            if isinstance(item, dict):
                name = str(item.get("place") or item.get("name") or "").strip()
            else:
                name = str(item or "").strip()
            if name and name not in places:
                places.append(name)
    return places


def _round_percentages(scores):
    if not scores:
        return []
    total = sum(scores)
    if total <= 0:
        base = [100.0 / len(scores)] * len(scores)
    else:
        base = [s * 100.0 / total for s in scores]
    floors = [int(x) for x in base]
    left = 100 - sum(floors)
    order = sorted(range(len(base)), key=lambda i: base[i] - floors[i], reverse=True)
    for i in order[:left]:
        floors[i] += 1
    return floors


def _ensure_video_contributions(plan: Optional[Dict]) -> Optional[Dict]:
    """根据 fused.txt 每个视频段与最终攻略地点的命中率，估算 video_contributions。"""
    if not plan:
        return plan
    fused_path = OUT_DIR / "fused.txt"
    if not fused_path.exists():
        return plan
    try:
        fused = fused_path.read_text(encoding="utf-8")
    except Exception:
        return plan
    sections = _extract_video_sections(fused)
    if not sections:
        return plan
    places = _collect_plan_places(plan)
    scores = []
    details = []
    for sec in sections:
        text = sec.get("text") or ""
        matched = []
        score = 0.0
        for place in places:
            if place and place in text:
                matched.append(place)
                score += 3.0
        content_len = min(len(text.strip()), 3000)
        score += max(0.2, content_len / 3000.0)
        scores.append(score)
        details.append({
            "filename": sec.get("filename") or f"视频 {sec.get('index', '')}",
            "matched_places": matched[:8],
            "evidence_count": len(matched),
        })
    percents = _round_percentages(scores)
    out = []
    for d, pct in zip(details, percents):
        d["contribution"] = pct
        out.append(d)
    plan["video_contributions"] = out
    return plan


# -------------------- 工具 --------------------
def _save_plan(plan: Dict) -> None:
    plan = _ensure_video_contributions(plan) or plan
    (OUT_DIR / "guide.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        from pipeline import render_markdown
        (OUT_DIR / "guide.md").write_text(render_markdown(plan), encoding="utf-8")
    except Exception as e:
        logger.warning("写 guide.md 失败：%s", e)
    try:
        (OUT_DIR / "map.html").write_text(
            render_map(plan, STATE.get("frames") or []), encoding="utf-8")
    except Exception as e:
        logger.warning("写 map.html 失败：%s", e)


SAMPLE_PATH = OUT_DIR / "guide_sample.json"   # 冻结的长三角样例（不被覆盖）
CURRENT_PATH = OUT_DIR / "guide.json"          # 当前/上次状态（生成/修改写入这里）


def _read_json(p: Path) -> Optional[Dict]:
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text("utf-8"))
    except Exception as e:
        logger.warning("读 %s 失败：%s", p.name, e)
        return None


def _load_existing_plan() -> Optional[Dict]:
    """优先读冻结样例（每次启动 = 长三角），样例缺失才退到 current。"""
    return _read_json(SAMPLE_PATH) or _read_json(CURRENT_PATH)


# -------------------- 路由 --------------------
@app.route("/")
def index():
    # 每次打开页面：把 STATE 重置回长三角样例
    sample = _read_json(SAMPLE_PATH)
    if sample is not None:
        STATE["plan"] = sample
    return render_template("index.html")


@app.route("/api/load_sample", methods=["GET", "POST"])
def api_load_sample():
    sample = _read_json(SAMPLE_PATH)
    if sample is None:
        return jsonify({"ok": False, "error": "未找到 guide_sample.json"}), 404
    STATE["plan"] = sample
    return jsonify({"ok": True, "plan": sample,
                    "missing": geocode.count_missing(sample)})


@app.route("/api/load_saved", methods=["GET", "POST"])
def api_load_saved():
    saved = _read_json(CURRENT_PATH)
    if saved is None:
        return jsonify({"ok": False, "error": "尚无保存的攻略"}), 404
    STATE["plan"] = saved
    return jsonify({"ok": True, "plan": saved,
                    "missing": geocode.count_missing(saved)})


@app.route("/api/save_current", methods=["POST"])
def api_save_current():
    plan = STATE["plan"]
    if plan is None:
        return jsonify({"ok": False, "error": "当前无内容可保存"}), 400
    _save_plan(plan)
    return jsonify({"ok": True})


@app.route("/api/plan", methods=["GET"])
def api_plan():
    plan = STATE["plan"]
    if plan is None:
        plan = _load_existing_plan()
        STATE["plan"] = plan
    if plan is None:
        return jsonify({"plan": None, "missing": 0})
    return jsonify({"plan": plan, "missing": geocode.count_missing(plan)})


@app.route("/api/map", methods=["GET"])
def api_map():
    """返回 folium 渲染的 HTML（用于 iframe srcdoc）。支持 ?style=soft|watercolor|standard|toner"""
    plan = STATE["plan"] or _load_existing_plan()
    if plan is None:
        return "<html><body style='font-family:sans-serif;padding:40px;'>" \
               "<h3>未加载任何攻略</h3><p>请先在右侧加载现有 JSON 或生成新攻略</p>" \
               "</body></html>"
    style = (request.args.get("style") or "soft").strip()
    return render_map(plan, STATE.get("frames") or [], style=style)


@app.route("/api/geocode", methods=["POST"])
def api_geocode():
    """给当前 plan 补全 lat/lng（AMap > LLM > Nominatim）。"""
    plan = STATE["plan"] or _load_existing_plan()
    if plan is None:
        return jsonify({"ok": False, "error": "尚未加载攻略"}), 400

    body = request.get_json(silent=True) or {}
    city = body.get("city") or plan.get("city") or ""
    amap_key = body.get("amap_key") or os.getenv("AMAP_KEY") or ""
    api_key = body.get("api_key") or os.getenv("VECTRUST_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
    base_url = body.get("base_url") or os.getenv("OPENAI_BASE_URL") or "https://api.openai-next.com"
    model = body.get("model") or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
    use_nominatim = bool(body.get("use_nominatim", False))

    try:
        geocode.enrich_plan(plan,
                            default_city=city,
                            amap_key=amap_key,
                            api_key=api_key,
                            base_url=base_url,
                            model=model,
                            use_nominatim=use_nominatim)
        STATE["plan"] = plan
        _save_plan(plan)
        return jsonify({"ok": True, "missing": geocode.count_missing(plan), "plan": plan})
    except Exception as e:
        logger.exception("geocode failed")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/memory", methods=["GET"])
def api_memory_list():
    """返回本地旅行记忆。记忆只保存在 output/travel_memory.json。"""
    memories = travel_memory.list_memories()
    return jsonify({"ok": True, "memories": memories, "count": len(memories)})


@app.route("/api/memory/reflect", methods=["POST"])
def api_memory_reflect():
    """把一次旅行复盘提炼成结构化旅行记忆并保存。"""
    body = request.get_json(silent=True) or {}
    review_text = (body.get("review_text") or "").strip()
    api_key = body.get("api_key") or os.getenv("VECTRUST_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
    base_url = body.get("base_url") or os.getenv("OPENAI_BASE_URL") or ""
    model = body.get("model") or os.getenv("OPENAI_MODEL") or ""

    if not review_text:
        return jsonify({"ok": False, "error": "请输入旅行复盘内容"}), 400
    if not api_key:
        return jsonify({"ok": False, "error": "缺少 API Key"}), 400

    try:
        from pipeline import DEFAULT_BASE_URL, DEFAULT_MODEL
        memory = travel_memory.extract_memory_with_llm(
            api_key=api_key,
            review_text=review_text,
            base_url=base_url or DEFAULT_BASE_URL,
            model=model or DEFAULT_MODEL,
        )
        saved = travel_memory.add_memory(memory)
        return jsonify({"ok": True, "memory": saved, "memories": travel_memory.list_memories()})
    except Exception as e:
        logger.exception("memory reflect failed")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/memory/retrieve", methods=["POST"])
def api_memory_retrieve():
    """根据本次旅行需求检索历史旅行记忆，便于调试和报告展示。"""
    body = request.get_json(silent=True) or {}
    try:
        result = travel_memory.retrieve_memories(
            body,
            max_results=int(body.get("max_results") or 3),
            memory_ids=_selected_memory_ids(body),
        )
        return jsonify({
            "ok": True,
            "context": result.get("context", ""),
            "matches": travel_memory.summarize_matches(result.get("matches") or []),
        })
    except Exception as e:
        logger.exception("memory retrieve failed")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/post-trip/records", methods=["GET"])
def api_post_trip_records():
    """返回旅行后记录。真实记录和派生偏好分开保存。"""
    records = post_trip.list_records()
    return jsonify({
        "ok": True,
        "records": records,
        "compact": post_trip.compact_records(records),
        "count": len(records),
    })


@app.route("/api/post-trip/records", methods=["POST"])
def api_post_trip_record_save():
    """保存一次真实旅行后记录，作为后续偏好提炼和攻略生成的事实源。"""
    body = request.get_json(silent=True) or {}
    plan = STATE["plan"] or _load_existing_plan()
    try:
        saved = post_trip.add_record(body, plan=plan)
        records = post_trip.list_records()
        return jsonify({
            "ok": True,
            "record": saved,
            "records": records,
            "compact": post_trip.compact_records(records),
        })
    except Exception as e:
        logger.exception("post-trip record save failed")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/post-trip/photos", methods=["POST"])
def api_post_trip_photos():
    """接收旅行后照片，保存到本地 output/post_trip_photos/。"""
    files = request.files.getlist("photos")
    if not files:
        single = request.files.get("photo")
        files = [single] if single else []
    files = [f for f in files if f and f.filename]
    if not files:
        return jsonify({"ok": False, "error": "未收到照片"}), 400

    import time
    import re as _re
    photo_dir = OUT_DIR / "post_trip_photos"
    photo_dir.mkdir(exist_ok=True)
    photos = []
    for idx, f in enumerate(files[:12], start=1):
        if f.mimetype and not f.mimetype.startswith("image/"):
            return jsonify({"ok": False, "error": f"不是图片文件：{f.filename}"}), 400
        suffix = Path(f.filename).suffix.lower() or ".jpg"
        if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic"}:
            suffix = ".jpg"
        stem = Path(f.filename).stem or "photo"
        stem = _re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff]+", "_", stem).strip("_")[:24] or "photo"
        safe_name = f"post_{int(time.time())}_{idx}_{stem}{suffix}"
        dst = photo_dir / safe_name
        f.save(str(dst))
        photos.append({
            "name": safe_name,
            "url": f"/output/post_trip_photos/{safe_name}",
            "size": dst.stat().st_size,
            "caption": "",
        })
    return jsonify({"ok": True, "photos": photos})


@app.route("/api/post-trip/guide", methods=["POST"])
def api_post_trip_guide():
    """基于真实旅行后记录生成可展示的旅行后攻略。"""
    body = request.get_json(silent=True) or {}
    api_key = body.get("api_key") or os.getenv("VECTRUST_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
    base_url = body.get("base_url") or os.getenv("OPENAI_BASE_URL") or ""
    model = body.get("model") or os.getenv("OPENAI_MODEL") or ""
    if not api_key:
        return jsonify({"ok": False, "error": "缺少 API Key"}), 400

    plan = STATE["plan"] or _load_existing_plan()
    record = _record_from_post_trip_body(body, plan)
    if not record:
        return jsonify({"ok": False, "error": "请先保存或填写旅行后记录"}), 400

    try:
        from pipeline import DEFAULT_BASE_URL, DEFAULT_MODEL
        plan_brief = json.dumps(post_trip.plan_snapshot(plan), ensure_ascii=False, indent=2)
        record_text = post_trip.record_review_text(record)
        fused = _read_output_text("fused.txt", max_chars=6000)
        transcript = _read_output_text("transcript.txt", max_chars=3000)
        user = (
            "请基于一次真实旅行后的记录，生成一份适合课程展示和普通读者阅读的旅行后攻略。\n\n"
            "要求：\n"
            "1. 用 Markdown 输出。\n"
            "2. 明确区分「原计划」与「实际体验」。\n"
            "3. 引用投递视频/融合素材中的线索，但不要编造不存在的来源。\n"
            "4. 包含真实路线、值得保留的安排、踩坑与修正建议、适合人群、预算/节奏复盘。\n"
            "5. 如果有照片素材，只按文件名或说明引用，不要假装看到了照片内容。\n\n"
            f"【原计划摘要】\n{plan_brief}\n\n"
            f"【旅行后记录】\n{record_text}\n\n"
            f"【投递视频融合素材节选】\n{fused or '无'}\n\n"
            f"【转写节选】\n{transcript or '无'}"
        )
        text = _llm_text(
            api_key,
            base_url=base_url or DEFAULT_BASE_URL,
            model=model or DEFAULT_MODEL,
            system="你是旅行复盘编辑，擅长把真实游玩记录整理成克制、可信、可执行的旅行攻略。",
            user=user,
        )
        (OUT_DIR / "post_trip_guide.md").write_text(text, encoding="utf-8")
        return jsonify({"ok": True, "guide": text, "record": record})
    except Exception as e:
        logger.exception("post-trip guide failed")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/post-trip/evaluate-video", methods=["POST"])
def api_post_trip_evaluate_video():
    """评价投递视频对实际旅行的参考价值。"""
    body = request.get_json(silent=True) or {}
    api_key = body.get("api_key") or os.getenv("VECTRUST_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
    base_url = body.get("base_url") or os.getenv("OPENAI_BASE_URL") or ""
    model = body.get("model") or os.getenv("OPENAI_MODEL") or ""
    if not api_key:
        return jsonify({"ok": False, "error": "缺少 API Key"}), 400

    plan = STATE["plan"] or _load_existing_plan()
    record = _record_from_post_trip_body(body, plan)
    if not record:
        return jsonify({"ok": False, "error": "请先保存或填写旅行后记录"}), 400

    try:
        from pipeline import DEFAULT_BASE_URL, DEFAULT_MODEL
        plan_brief = json.dumps(post_trip.plan_snapshot(plan), ensure_ascii=False, indent=2)
        record_text = post_trip.record_review_text(record)
        fused = _read_output_text("fused.txt", max_chars=7000)
        user = (
            "请评价投递视频对这次实际旅行的参考价值，输出 Markdown。\n\n"
            "必须包含这四个小节：\n"
            "## 视频推荐靠谱的地方\n"
            "## 视频滤镜或信息不足的地方\n"
            "## 实地超预期或个人发现\n"
            "## 下次规划应该如何修正\n\n"
            "评价要基于证据：原计划、视频融合素材、实际旅行后记录。不要假装知道视频画面之外的信息。\n\n"
            f"【原计划摘要与视频贡献】\n{plan_brief}\n\n"
            f"【旅行后记录】\n{record_text}\n\n"
            f"【投递视频融合素材节选】\n{fused or '无'}"
        )
        text = _llm_text(
            api_key,
            base_url=base_url or DEFAULT_BASE_URL,
            model=model or DEFAULT_MODEL,
            system="你是短视频旅行信息审稿人，擅长比较种草内容、AI 计划和真实体验之间的差距。",
            user=user,
        )
        (OUT_DIR / "post_trip_video_evaluation.md").write_text(text, encoding="utf-8")
        return jsonify({"ok": True, "evaluation": text, "record": record})
    except Exception as e:
        logger.exception("post-trip video evaluation failed")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/revise", methods=["POST"])
def api_revise():
    body = request.get_json(silent=True) or {}
    instr = (body.get("instruction") or "").strip()
    api_key = body.get("api_key") or os.getenv("VECTRUST_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
    base_url = body.get("base_url") or os.getenv("OPENAI_BASE_URL") or ""
    model = body.get("model") or os.getenv("OPENAI_MODEL") or ""
    use_memory = _as_bool(body.get("use_memory"), False)

    if not instr:
        return jsonify({"ok": False, "error": "请输入修改诉求"}), 400
    if not api_key:
        return jsonify({"ok": False, "error": "缺少 API Key"}), 400

    plan = STATE["plan"] or _load_existing_plan()
    if plan is None:
        return jsonify({"ok": False, "error": "尚未加载攻略"}), 400

    try:
        from pipeline import revise_plan, optimize_routes, DEFAULT_BASE_URL, DEFAULT_MODEL
        memory_retrieval = None
        effective_instr = instr
        if use_memory:
            memory_retrieval = travel_memory.retrieve_memories(
                _memory_query_from_revise(plan, instr),
                max_results=3,
                memory_ids=_selected_memory_ids(body),
            )
            effective_instr = _inject_memory_text(instr, memory_retrieval.get("context", ""))

        new_plan = revise_plan(api_key, plan, effective_instr,
                               base_url=base_url or DEFAULT_BASE_URL,
                               model=model or DEFAULT_MODEL)
        # 修改后也跑一遍路线优化
        new_plan = optimize_routes(new_plan)
        travel_memory.annotate_plan_with_memory(new_plan, memory_retrieval)
        STATE["plan"] = new_plan
        _save_plan(new_plan)
        return jsonify({"ok": True, "plan": new_plan,
                        "missing": geocode.count_missing(new_plan)})
    except Exception as e:
        logger.exception("revise failed")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/generate", methods=["POST"])
def api_generate():
    """异步调度 run_pipeline。立刻返回，前端轮询 /api/job。

    body 支持：
      - share_text: 抖音分享文案 / 链接
      - local_video: 单视频路径（兼容旧调用）
      - local_videos: 多视频路径列表，最多 MAX_UPLOAD_FILES 个
    至少需提供一项。
    """
    body = request.get_json(silent=True) or {}
    share = (body.get("share_text") or "").strip()
    local_video = (body.get("local_video") or "").strip()
    raw_local_videos = body.get("local_videos") or body.get("local_video_paths") or []
    if isinstance(raw_local_videos, str):
        local_videos = [raw_local_videos] if raw_local_videos.strip() else []
    else:
        local_videos = [str(x).strip() for x in raw_local_videos if str(x).strip()]
    if local_video and local_video not in local_videos:
        local_videos.insert(0, local_video)
    local_videos = local_videos[:MAX_UPLOAD_FILES]
    api_key = body.get("api_key") or os.getenv("VECTRUST_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
    base_url = body.get("base_url") or os.getenv("OPENAI_BASE_URL") or ""
    model = body.get("model") or os.getenv("OPENAI_MODEL") or ""
    days = int(body.get("days") or 2)
    budget = float(body.get("budget") or 500)
    n_frames = int(body.get("n_frames") or 5)
    people = int(body.get("people") or 2)
    travel_style = (body.get("travel_style") or "轻松型").strip()
    target_group = (body.get("target_group") or "大人").strip()
    extra = (body.get("extra") or "").strip()
    themes_raw = body.get("themes") or []
    if isinstance(themes_raw, str):
        themes = [t.strip() for t in themes_raw.split(",") if t.strip()]
    else:
        themes = [str(t).strip() for t in themes_raw if str(t).strip()]
    do_geocode = _as_bool(body.get("geocode"), True)
    use_memory = _as_bool(body.get("use_memory"), False)

    if not share and not local_videos:
        return jsonify({"ok": False, "error": "请粘贴抖音文案 或 提供本地视频"}), 400
    if not api_key:
        return jsonify({"ok": False, "error": "缺少 API Key"}), 400

    # 解析本地视频路径（相对 → 绝对）
    abs_local_videos = []
    for item in local_videos:
        p = Path(item)
        if not p.is_absolute():
            p = BASE_DIR / item
        if not p.exists():
            return jsonify({"ok": False, "error": f"本地视频不存在：{p}"}), 400
        abs_local_videos.append(str(p))
    local_video = abs_local_videos[0] if abs_local_videos else ""

    memory_retrieval = None
    effective_extra = extra
    if use_memory:
        memory_retrieval = travel_memory.retrieve_memories(
            _memory_query_from_generate(body, share=share, themes=themes),
            max_results=3,
            memory_ids=_selected_memory_ids(body),
        )
        effective_extra = _inject_memory_text(extra, memory_retrieval.get("context", ""))

    with STATE["lock"]:
        if _job_is_active():
            return jsonify({"ok": False, "error": "已有任务运行中"}), 409
        control = JobControl()
        STATE["control"] = control
        STATE["job"] = {"status": "running", "step": "排队中…", "logs": [],
                        "error": "", "paused": False}

    def worker():
        from pipeline import run_pipeline, DEFAULT_BASE_URL, DEFAULT_MODEL

        def cb(msg: str):
            # 协作式 pause/cancel：每步都先过一遍闸
            control.check()
            # 空字符串 = 心跳（只用于让 worker 在并行解析时及早响应取消）
            if not msg:
                return
            STATE["job"]["step"] = msg
            STATE["job"]["paused"] = control.paused
            STATE["job"]["logs"].append(msg)
            logger.info("[pipeline] %s", msg)

        try:
            result = run_pipeline(
                share, api_key,
                days=days, budget=budget,
                base_url=base_url or DEFAULT_BASE_URL,
                model=model or DEFAULT_MODEL,
                n_frames=n_frames, progress=cb,
                local_video=local_video or None,
                local_videos=abs_local_videos or None,
                people=people,
                travel_style=travel_style,
                target_group=target_group,
                extra=effective_extra,
                themes=themes,
            )
            plan = result["plan"]
            travel_memory.annotate_plan_with_memory(plan, memory_retrieval)
            STATE["frames"] = result.get("frames") or []

            # 新版多视频流程已自带坐标；只在缺失时才走老地理编码
            if do_geocode and (not result.get("points")) and geocode.count_missing(plan) > 0:
                cb("地理编码补全坐标…")
                geocode.enrich_plan(plan,
                                    default_city=plan.get("city", ""),
                                    amap_key=os.getenv("AMAP_KEY", ""),
                                    api_key=api_key,
                                    base_url=base_url or DEFAULT_BASE_URL,
                                    model=model or DEFAULT_MODEL)

            STATE["plan"] = plan
            _save_plan(plan)
            STATE["job"]["status"] = "done"
            STATE["job"]["step"] = "✅ 完成"
            STATE["job"]["paused"] = False
        except JobCancelled:
            logger.info("pipeline cancelled by user")
            STATE["job"]["status"] = "cancelled"
            STATE["job"]["step"] = "🛑 已终止"
            STATE["job"]["paused"] = False
        except Exception as e:
            logger.exception("pipeline failed")
            STATE["job"]["status"] = "error"
            STATE["job"]["error"] = str(e)
            STATE["job"]["paused"] = False

    t = threading.Thread(target=worker, daemon=True)
    control.thread = t
    t.start()
    return jsonify({"ok": True})


@app.route("/api/job", methods=["GET"])
def api_job():
    job = STATE.get("job")
    if not job:
        return jsonify({"status": "idle", "step": "", "logs": [], "error": "", "paused": False})
    # 检测僵尸 running：线程已不在了但状态没更新——前端按 idle 处理，允许重新提交
    ctl: Optional[JobControl] = STATE.get("control")
    if job.get("status") in ("running", "paused"):
        t = ctl.thread if ctl else None
        if t is None or not t.is_alive():
            job["status"] = "error"
            if not job.get("error"):
                job["error"] = "任务进程已退出（可能上次启动时崩溃）"
            job["paused"] = False
    return jsonify(job)


@app.route("/api/job/control", methods=["POST"])
def api_job_control():
    """暂停 / 继续 / 终止当前任务。

    body: {"action": "pause" | "resume" | "cancel"}
    """
    body = request.get_json(silent=True) or {}
    action = (body.get("action") or "").strip().lower()
    job = STATE.get("job")
    ctl: Optional[JobControl] = STATE.get("control")

    if action == "cancel":
        # 即便没有活跃任务也允许"清场"——把残留的 running 状态清掉
        if ctl is not None:
            ctl.cancel_event.set()
            ctl.pause_event.set()  # 解除阻塞，让 worker 能跑到 check() 并抛出
        if job and job.get("status") in ("running", "paused"):
            job["step"] = "🛑 正在终止…"
            job["paused"] = False
        elif job:
            # 已结束的旧状态——直接重置为 idle
            STATE["job"] = None
            STATE["control"] = None
        return jsonify({"ok": True})

    if not job or job.get("status") not in ("running", "paused") or ctl is None:
        return jsonify({"ok": False, "error": "当前没有运行中的任务"}), 400

    if action == "pause":
        ctl.pause_event.clear()
        job["status"] = "paused"
        job["paused"] = True
        job["step"] = "⏸ 已暂停（下一步起停止）"
        return jsonify({"ok": True})

    if action == "resume":
        ctl.pause_event.set()
        job["status"] = "running"
        job["paused"] = False
        return jsonify({"ok": True})

    return jsonify({"ok": False, "error": f"未知操作：{action}"}), 400


@app.route("/api/reload", methods=["POST"])
def api_reload():
    plan = _load_existing_plan()
    STATE["plan"] = plan
    return jsonify({"ok": plan is not None,
                    "plan": plan,
                    "missing": geocode.count_missing(plan) if plan else 0})


@app.route("/output/<path:filename>")
def output_file(filename):
    return send_from_directory(str(OUT_DIR), filename)


@app.route("/api/export", methods=["GET"])
def api_export():
    """把当前 output/ 里的攻略 + 地图 + Markdown + 关键帧打包成 zip 下载。"""
    import zipfile, io
    plan = STATE["plan"] or _load_existing_plan()
    if plan is None:
        return jsonify({"ok": False, "error": "尚未生成攻略"}), 400

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        # 主要文件
        for name in ("guide.json", "guide.md", "map.html", "transcript.txt", "fused.txt"):
            p = OUT_DIR / name
            if p.exists():
                zf.write(p, arcname=name)
        # 关键帧
        frames_dir = OUT_DIR / "frames"
        if frames_dir.exists():
            for fp in sorted(frames_dir.glob("frame_*.jpg")):
                zf.write(fp, arcname=f"frames/{fp.name}")
        # README
        title = plan.get("title", "旅行攻略")
        city = plan.get("city", "")
        days = plan.get("days", "?")
        readme = (
            f"# {title}\n\n"
            f"- 城市：{city}\n- 天数：{days}\n"
            f"- 由「抖音旅行图鉴」生成\n\n"
            f"## 包内容\n"
            f"- guide.json / guide.md ：结构化攻略 & Markdown\n"
            f"- map.html ：可在浏览器打开的离线地图\n"
            f"- transcript.txt / fused.txt ：原始转写/融合文本\n"
            f"- frames/ ：关键帧截图\n"
        )
        zf.writestr("README.md", readme)

    buf.seek(0)
    from flask import send_file
    fname = (plan.get("title") or "travel_atlas").replace(" ", "_")
    return send_file(
        buf, mimetype="application/zip", as_attachment=True,
        download_name=f"{fname}.zip",
    )


@app.route("/api/upload", methods=["POST"])
def api_upload():
    """接收前端上传的视频文件，存到 output/uploads/，返回服务器端绝对路径。"""
    f = request.files.get("video")
    if not f or not f.filename:
        return jsonify({"ok": False, "error": "未收到文件"}), 400
    up_dir = OUT_DIR / "uploads"
    up_dir.mkdir(exist_ok=True)
    # 保留扩展名
    suffix = Path(f.filename).suffix or ".mp4"
    safe_name = f"upload_{int(__import__('time').time())}{suffix}"
    dst = up_dir / safe_name
    f.save(str(dst))
    return jsonify({"ok": True, "path": str(dst), "size": dst.stat().st_size, "name": safe_name})


@app.route("/api/env", methods=["GET"])
def api_env():
    """前端展示环境检查。"""
    import shutil as _sh
    return jsonify({
        "yt_dlp": bool(_sh.which("yt-dlp")),
        "ffmpeg": bool(_sh.which("ffmpeg")),
        "ffprobe": bool(_sh.which("ffprobe")),
        "has_api_key": bool(os.getenv("VECTRUST_API_KEY") or os.getenv("OPENAI_API_KEY")),
        "default_base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai-next.com"),
        "default_model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    })


if __name__ == "__main__":
    # 启动时尝试加载已有 plan，方便直接看地图
    STATE["plan"] = _load_existing_plan()
    if STATE["plan"]:
        logger.info("已加载现有 guide.json（缺失坐标 %d 个）",
                    geocode.count_missing(STATE["plan"]))
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "5000"))
    logger.info("🌐 http://%s:%s", host, port)
    app.run(host=host, port=port, debug=False, threaded=True)
