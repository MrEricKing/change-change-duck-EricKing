# -*- coding: utf-8 -*-
"""Post-trip records, stored separately from derived travel memories."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional


BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR / "output"
RECORD_PATH = OUT_DIR / "post_trip_records.json"
RECORD_VERSION = 1


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _split_text_list(value) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, tuple):
        return [str(x).strip() for x in value if str(x).strip()]
    text = str(value).strip()
    if not text:
        return []
    parts = re.split(r"[\n,，、;；]+", text)
    return [p.strip() for p in parts if p.strip()]


def _stable_id(record: Dict) -> str:
    seed = "|".join([
        str(record.get("title") or ""),
        str(record.get("review_text") or ""),
        str(record.get("created_at") or _now_iso()),
    ])
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]
    return f"{str(record.get('created_at') or _now_iso())[:10]}-{digest}"


def load_store(path: Path = RECORD_PATH) -> Dict:
    if not path.exists():
        return {"version": RECORD_VERSION, "records": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": RECORD_VERSION, "records": []}
    records = data.get("records")
    if not isinstance(records, list):
        records = []
    return {"version": int(data.get("version") or RECORD_VERSION), "records": records}


def save_store(store: Dict, path: Path = RECORD_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": int(store.get("version") or RECORD_VERSION),
        "records": [normalize_record(r) for r in store.get("records", [])],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def list_records(path: Path = RECORD_PATH) -> List[Dict]:
    store = load_store(path)
    return [normalize_record(r) for r in store.get("records", [])]


def plan_snapshot(plan: Optional[Dict]) -> Dict:
    if not plan:
        return {}
    places: List[str] = []
    for day in plan.get("itinerary", []) or []:
        for stop in day.get("stops", []) or []:
            name = str(stop.get("place") or "").strip()
            if name and name not in places:
                places.append(name)
    summary = plan.get("summary") or {}
    return {
        "title": plan.get("title") or "",
        "city": plan.get("city") or "",
        "days": plan.get("days"),
        "people": plan.get("people"),
        "travel_style": plan.get("travel_style") or summary.get("travel_style") or "",
        "total_cost": summary.get("total_cost"),
        "route_logic": summary.get("route_logic") or "",
        "planned_places": places,
        "video_contributions": plan.get("video_contributions") or plan.get("material_contributions") or [],
    }


def normalize_photo(photo: Dict) -> Dict:
    photo = dict(photo or {})
    return {
        "name": str(photo.get("name") or "").strip(),
        "url": str(photo.get("url") or "").strip(),
        "size": int(photo.get("size") or 0),
        "caption": str(photo.get("caption") or "").strip(),
    }


def normalize_record(record: Dict, *, plan: Optional[Dict] = None) -> Dict:
    record = dict(record or {})
    record.setdefault("created_at", _now_iso())
    snapshot = record.get("linked_plan") or plan_snapshot(plan)
    default_title = ""
    if snapshot.get("title"):
        default_title = f"{snapshot['title']}真实复盘"
    record["title"] = str(record.get("title") or default_title or "未命名旅行后记录").strip()
    record["actual_places"] = _split_text_list(record.get("actual_places"))
    record["skipped_places"] = _split_text_list(record.get("skipped_places"))
    record["added_places"] = _split_text_list(record.get("added_places"))
    record["actual_cost"] = str(record.get("actual_cost") or "").strip()
    record["actual_pace"] = str(record.get("actual_pace") or "").strip()
    record["review_text"] = str(record.get("review_text") or "").strip()
    record["photos"] = [normalize_photo(p) for p in record.get("photos", []) if isinstance(p, dict)]
    record["linked_plan"] = snapshot
    record["id"] = str(record.get("id") or _stable_id(record)).strip()
    return record


def add_record(record: Dict, *, plan: Optional[Dict] = None, path: Path = RECORD_PATH) -> Dict:
    normalized = normalize_record(record, plan=plan)
    store = load_store(path)
    records = [normalize_record(r) for r in store.get("records", [])]
    records = [r for r in records if r.get("id") != normalized["id"]]
    records.insert(0, normalized)
    save_store({"version": RECORD_VERSION, "records": records}, path)
    return normalized


def get_record(record_id: str, *, path: Path = RECORD_PATH) -> Optional[Dict]:
    for record in list_records(path):
        if record.get("id") == record_id:
            return record
    return None


def latest_record(*, path: Path = RECORD_PATH) -> Optional[Dict]:
    records = list_records(path)
    return records[0] if records else None


def record_review_text(record: Dict) -> str:
    record = normalize_record(record)
    sections = [
        f"标题：{record.get('title')}",
        f"实际花费：{record.get('actual_cost') or '未记录'}",
        f"实际节奏：{record.get('actual_pace') or '未记录'}",
    ]
    for label, key in (
        ("实际去了", "actual_places"),
        ("没去成", "skipped_places"),
        ("新增发现", "added_places"),
    ):
        values = record.get(key) or []
        if values:
            sections.append(f"{label}：" + "、".join(values))
    if record.get("review_text"):
        sections.append("真实体验：" + record["review_text"])
    photos = [p.get("name") for p in record.get("photos") or [] if p.get("name")]
    if photos:
        sections.append("照片素材：" + "、".join(photos[:8]))
    return "\n".join(sections)


def compact_records(records: Iterable[Dict], *, limit: int = 12) -> List[Dict]:
    out = []
    for record in list(records or [])[:limit]:
        r = normalize_record(record)
        out.append({
            "id": r.get("id"),
            "title": r.get("title"),
            "created_at": r.get("created_at"),
            "actual_places": r.get("actual_places")[:5],
            "skipped_places": r.get("skipped_places")[:3],
            "added_places": r.get("added_places")[:3],
            "actual_cost": r.get("actual_cost"),
            "actual_pace": r.get("actual_pace"),
            "photo_count": len(r.get("photos") or []),
            "linked_plan_title": (r.get("linked_plan") or {}).get("title"),
        })
    return out
