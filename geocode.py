# -*- coding: utf-8 -*-
"""
地理编码：给 guide.json 中缺失 lat/lng 的 stop 补坐标。

三级兜底：
1. AMap 高德 Web 服务（设置环境变量 AMAP_KEY）—— 国内访问稳定
2. LLM 批量补坐标 —— 复用 OpenAI 兼容 API Key
3. Nominatim OSM —— 海外/兜底

高德返回 GCJ-02，会转为 WGS-84（与 OSM/CartoDB 瓦片一致）。
结果缓存到 output/geocache.json。
"""
from __future__ import annotations

import json
import math
import os
import time
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

CACHE_PATH = Path(__file__).with_name("output") / "geocache.json"

# -------------------- 坐标系转换 GCJ02 → WGS84 --------------------
_A = 6378245.0
_EE = 0.00669342162296594323


def _out_of_china(lng: float, lat: float) -> bool:
    return not (72.004 < lng < 137.8347 and 0.8293 < lat < 55.8271)


def _transform_lat(x: float, y: float) -> float:
    ret = -100 + 2*x + 3*y + 0.2*y*y + 0.1*x*y + 0.2*math.sqrt(abs(x))
    ret += (20*math.sin(6*x*math.pi) + 20*math.sin(2*x*math.pi)) * 2/3
    ret += (20*math.sin(y*math.pi) + 40*math.sin(y/3*math.pi)) * 2/3
    ret += (160*math.sin(y/12*math.pi) + 320*math.sin(y*math.pi/30)) * 2/3
    return ret


def _transform_lng(x: float, y: float) -> float:
    ret = 300 + x + 2*y + 0.1*x*x + 0.1*x*y + 0.1*math.sqrt(abs(x))
    ret += (20*math.sin(6*x*math.pi) + 20*math.sin(2*x*math.pi)) * 2/3
    ret += (20*math.sin(x*math.pi) + 40*math.sin(x/3*math.pi)) * 2/3
    ret += (150*math.sin(x/12*math.pi) + 300*math.sin(x/30*math.pi)) * 2/3
    return ret


def gcj02_to_wgs84(lng: float, lat: float) -> Tuple[float, float]:
    if _out_of_china(lng, lat):
        return lng, lat
    dlat = _transform_lat(lng-105, lat-35)
    dlng = _transform_lng(lng-105, lat-35)
    radlat = lat / 180 * math.pi
    magic = math.sin(radlat)
    magic = 1 - _EE*magic*magic
    sqrtmagic = math.sqrt(magic)
    dlat = dlat*180 / ((_A*(1-_EE))/(magic*sqrtmagic)*math.pi)
    dlng = dlng*180 / (_A/sqrtmagic*math.cos(radlat)*math.pi)
    return lng - dlng, lat - dlat


# -------------------- 缓存 --------------------
def _load_cache() -> Dict[str, Tuple[float, float]]:
    if CACHE_PATH.exists():
        try:
            return {k: tuple(v) for k, v in json.loads(CACHE_PATH.read_text("utf-8")).items()}
        except Exception:
            return {}
    return {}


def _save_cache(cache: Dict[str, Tuple[float, float]]) -> None:
    CACHE_PATH.parent.mkdir(exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps({k: list(v) for k, v in cache.items()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# -------------------- 单点查询 --------------------
def geocode_amap(query: str, city: str = "", key: str = "") -> Optional[Tuple[float, float]]:
    """AMap 高德。返回 GCJ-02 (lat, lng)，与本系统使用的高德瓦片底图原生对齐。"""
    key = key or os.getenv("AMAP_KEY") or ""
    if not key:
        return None
    import requests
    try:
        r = requests.get(
            "https://restapi.amap.com/v3/geocode/geo",
            params={"key": key, "address": query, "city": city or "", "output": "JSON"},
            timeout=8, proxies={"http": None, "https": None},
        )
        data = r.json()
        if data.get("status") != "1" or not data.get("geocodes"):
            return None
        loc = data["geocodes"][0].get("location") or ""
        if "," not in loc:
            return None
        lng_gcj, lat_gcj = (float(x) for x in loc.split(","))
        # 不转换；保留 GCJ-02 给高德瓦片直接用
        return lat_gcj, lng_gcj
    except Exception as e:
        logger.warning("amap '%s' failed: %s", query, e)
        return None


def geocode_nominatim(query: str, geolocator=None) -> Optional[Tuple[float, float]]:
    from geopy.geocoders import Nominatim
    geolocator = geolocator or Nominatim(user_agent="douyin-travel-guide/1.0", timeout=10)
    try:
        loc = geolocator.geocode(query, language="zh")
        if loc:
            return float(loc.latitude), float(loc.longitude)
    except Exception as e:
        logger.warning("nominatim '%s' failed: %s", query, e)
    return None


# -------------------- LLM 兜底 --------------------
def geocode_via_llm(plan: Dict, api_key: str, base_url: str, model: str) -> Dict:
    """让 LLM 直接给所有缺坐标的 stop 补 lat/lng（WGS84）。"""
    import requests
    missing: List[str] = []
    for day in plan.get("itinerary", []) or []:
        for stop in day.get("stops", []) or []:
            try:
                float(stop.get("lat")); float(stop.get("lng"))
            except (TypeError, ValueError):
                missing.append(stop.get("place") or "")

    if not missing:
        return {}

    city = plan.get("city") or ""
    prompt = (
        f"以下是『{city or '未知地区'}』的景点 / 店铺 / 打卡点列表。"
        f"请输出每个地点的 WGS84 坐标（普通 GPS 经纬度，不是火星坐标）。"
        f"必须严格返回 JSON 对象，键为地点名（与输入完全一致），值为 [lat, lng] 数组，"
        f"无法定位的写 null。不要任何额外文字。\n"
        f"地点列表：{json.dumps(missing, ensure_ascii=False)}"
    )
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是熟悉全球地理的助手。只输出严格 JSON。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    url = base_url.rstrip("/") + "/v1/chat/completions"
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=body, timeout=60, proxies={"http": None, "https": None},
    )
    if r.status_code != 200 and "response_format" in r.text:
        body.pop("response_format", None)
        r = requests.post(url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body, timeout=60, proxies={"http": None, "https": None})
    if r.status_code != 200:
        raise RuntimeError(f"LLM geocode failed {r.status_code}: {r.text[:300]}")

    content = r.json()["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.lower().startswith("json"):
            content = content[4:].lstrip()
    coords = json.loads(content)
    return {k: tuple(v) for k, v in coords.items() if isinstance(v, (list, tuple)) and len(v) == 2}


# -------------------- 批量补全主入口 --------------------
def enrich_plan(plan: Dict, *,
                default_city: str = "",
                amap_key: str = "",
                api_key: str = "",
                base_url: str = "",
                model: str = "",
                use_nominatim: bool = False,
                sleep: float = 1.1) -> Dict:
    """就地补全 plan 中所有 stop 的 lat/lng。优先级 AMap > LLM > Nominatim。"""
    cache = _load_cache()
    amap_key = amap_key or os.getenv("AMAP_KEY") or ""
    city = plan.get("city") or default_city
    if city and not plan.get("city"):
        plan["city"] = city

    # 第一步：先用缓存 + AMap
    needs_llm: List[str] = []
    for day in plan.get("itinerary", []) or []:
        for stop in day.get("stops", []) or []:
            try:
                float(stop.get("lat")); float(stop.get("lng"))
                continue
            except (TypeError, ValueError):
                pass
            place = (stop.get("place") or "").strip()
            if not place:
                continue
            key = f"{city}|{place}" if city else place
            if key in cache:
                stop["lat"], stop["lng"] = cache[key]
                continue
            if amap_key:
                coord = geocode_amap(place, city=city, key=amap_key)
                if coord:
                    stop["lat"], stop["lng"] = coord
                    cache[key] = coord
                    continue
            needs_llm.append((day, stop, place, key))

    # 第二步：LLM 一次性补齐剩余
    if needs_llm and api_key:
        try:
            coords = geocode_via_llm(plan, api_key, base_url, model)
            for day, stop, place, key in list(needs_llm):
                if place in coords:
                    stop["lat"], stop["lng"] = coords[place]
                    cache[key] = coords[place]
                    needs_llm.remove((day, stop, place, key))
        except Exception as e:
            logger.warning("LLM geocode 失败：%s", e)

    # 第三步：Nominatim 兜底
    if needs_llm and use_nominatim:
        from geopy.geocoders import Nominatim
        geolocator = Nominatim(user_agent="douyin-travel-guide/1.0", timeout=10)
        for day, stop, place, key in needs_llm:
            candidates = []
            if city:
                candidates.append(f"{place}, {city}, China")
            candidates.append(place)
            for q in candidates:
                coord = geocode_nominatim(q, geolocator)
                time.sleep(sleep)
                if coord:
                    stop["lat"], stop["lng"] = coord
                    cache[key] = coord
                    break

    _save_cache(cache)
    return plan


def count_missing(plan: Dict) -> int:
    n = 0
    for day in plan.get("itinerary", []) or []:
        for stop in day.get("stops", []) or []:
            try:
                float(stop.get("lat")); float(stop.get("lng"))
            except (TypeError, ValueError):
                n += 1
    return n


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "output/guide.json")
    plan = json.loads(path.read_text("utf-8"))
    print(f"待补全：{count_missing(plan)} 个")
    enrich_plan(plan,
                default_city=plan.get("city", ""),
                amap_key=os.getenv("AMAP_KEY", ""),
                api_key=os.getenv("OPENAI_API_KEY") or os.getenv("VECTRUST_API_KEY", ""),
                base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com"),
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"剩余缺失：{count_missing(plan)} 个 → 写回 {path}")
