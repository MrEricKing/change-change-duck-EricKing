# -*- coding: utf-8 -*-
"""
Folium 地图渲染：
- 中国境内默认高德 GCJ-02 底图；海外自动切 OSM
- WGS-84 ↔ GCJ-02 自动转换，保证 marker 与底图对齐
- 用 OSRM 真实路网生成沿路曲线（不再直线连接）
- 大号 emoji 贴纸 marker + 永久地名 + 点击 postMessage 联动右栏
- 跨天连接：彩色虚线 + 交通模式标签
"""
import math
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import folium
import requests

logger = logging.getLogger(__name__)

DAY_COLORS = ["#F08A6A", "#3FA6E0", "#7CB05A", "#F5C84B",
              "#9C7BD9", "#4FB3A9", "#E48AAB"]


# ============================================================
# WGS-84 (GPS) ↔ GCJ-02 (高德/腾讯) 坐标系转换
# ============================================================
_A_AXIS = 6378245.0
_EE = 0.00669342162296594323

def _out_of_china(lng: float, lat: float) -> bool:
    return not (72.004 < lng < 137.8347 and 0.8293 < lat < 55.8271)

def _t_lat(x: float, y: float) -> float:
    ret = -100 + 2*x + 3*y + 0.2*y*y + 0.1*x*y + 0.2*math.sqrt(abs(x))
    ret += (20*math.sin(6*x*math.pi) + 20*math.sin(2*x*math.pi)) * 2/3
    ret += (20*math.sin(y*math.pi) + 40*math.sin(y/3*math.pi)) * 2/3
    ret += (160*math.sin(y/12*math.pi) + 320*math.sin(y*math.pi/30)) * 2/3
    return ret

def _t_lng(x: float, y: float) -> float:
    ret = 300 + x + 2*y + 0.1*x*x + 0.1*x*y + 0.1*math.sqrt(abs(x))
    ret += (20*math.sin(6*x*math.pi) + 20*math.sin(2*x*math.pi)) * 2/3
    ret += (20*math.sin(x*math.pi) + 40*math.sin(x/3*math.pi)) * 2/3
    ret += (150*math.sin(x/12*math.pi) + 300*math.sin(x/30*math.pi)) * 2/3
    return ret

def wgs84_to_gcj02(lat: float, lng: float) -> Tuple[float, float]:
    if _out_of_china(lng, lat):
        return lat, lng
    dlat = _t_lat(lng-105, lat-35); dlng = _t_lng(lng-105, lat-35)
    radlat = lat / 180 * math.pi
    magic = math.sin(radlat); magic = 1 - _EE*magic*magic
    sqrtmagic = math.sqrt(magic)
    dlat = dlat*180 / ((_A_AXIS*(1-_EE))/(magic*sqrtmagic)*math.pi)
    dlng = dlng*180 / (_A_AXIS/sqrtmagic*math.cos(radlat)*math.pi)
    return lat + dlat, lng + dlng

def gcj02_to_wgs84(lat: float, lng: float) -> Tuple[float, float]:
    if _out_of_china(lng, lat):
        return lat, lng
    new_lat, new_lng = wgs84_to_gcj02(lat, lng)
    return lat * 2 - new_lat, lng * 2 - new_lng


# ============================================================
# OSRM 路网（真实道路曲线，缓存避免重复请求）
# ============================================================
_ROUTE_CACHE: Dict[tuple, Optional[List[Tuple[float, float]]]] = {}

def fetch_road_polyline(coords_wgs84: List[Tuple[float, float]],
                        profile: str = "driving") -> Optional[List[Tuple[float, float]]]:
    """OSRM public demo: 用真实路网串起来。失败 → None（调用方画直线）"""
    if len(coords_wgs84) < 2:
        return None
    key = (profile, tuple((round(la, 5), round(ln, 5)) for la, ln in coords_wgs84))
    if key in _ROUTE_CACHE:
        return _ROUTE_CACHE[key]
    coord_str = ";".join(f"{ln:.6f},{la:.6f}" for la, ln in coords_wgs84)
    url = f"https://router.project-osrm.org/route/v1/{profile}/{coord_str}"
    try:
        r = requests.get(
            url, params={"overview": "full", "geometries": "geojson"},
            timeout=8, proxies={"http": None, "https": None},
        )
        if r.status_code != 200:
            _ROUTE_CACHE[key] = None
            return None
        data = r.json()
        if data.get("code") != "Ok" or not data.get("routes"):
            _ROUTE_CACHE[key] = None
            return None
        coords = data["routes"][0]["geometry"]["coordinates"]
        poly = [(lat, lng) for lng, lat in coords]
        _ROUTE_CACHE[key] = poly
        return poly
    except Exception as e:
        logger.info("OSRM 失败：%s（回退直线）", e)
        _ROUTE_CACHE[key] = None
        return None


def _collect_points(plan: Dict) -> List[Dict]:
    out: List[Dict] = []
    for day in plan.get("itinerary", []) or []:
        d = day.get("day", 0) or 0
        for stop in day.get("stops", []) or []:
            lat = stop.get("lat"); lng = stop.get("lng")
            if lat is None or lng is None:
                continue
            try:
                lat = float(lat); lng = float(lng)
            except (TypeError, ValueError):
                continue
            out.append({"day": d, **stop, "lat": lat, "lng": lng})
    return out


def _is_overseas(points: List[Dict]) -> bool:
    """检查是否有任意点在中国大陆/港澳台范围外（粗略检测）"""
    for p in points:
        lat, lng = p["lat"], p["lng"]
        # 中国大致范围（含港澳台）
        if not (18 <= lat <= 53.5 and 73 <= lng <= 135):
            return True
    return False


def render_map(plan: Dict, frames: Optional[List[Path]] = None,
               style: str = "soft") -> str:
    """
    自动按区域选底图：
    - 任意 stop 在中国境内 → 默认高德地图（GCJ-02 原生，国内细节最好）
    - 全部 stop 在海外 → 默认 OpenStreetMap（全球覆盖）
    用户可右上角 LayerControl 手动切换
    """
    points = _collect_points(plan)
    if not points:
        return _empty_map_html(plan)

    center = [sum(p["lat"] for p in points) / len(points),
              sum(p["lng"] for p in points) / len(points)]

    overseas = _is_overseas(points)

    m = folium.Map(
        location=center,
        zoom_start=11,
        tiles=None,
        control_scale=False,
        zoom_control=True,
    )

    # 1. 高德地图（GCJ-02 火星坐标系，中国大陆细节最好）
    folium.TileLayer(
        tiles="https://webrd01.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}",
        attr="© 高德地图 AMap",
        name="🇨🇳 高德地图",
        max_zoom=18,
        subdomains=["01", "02", "03", "04"],
        show=not overseas,
    ).add_to(m)

    # 2. OpenStreetMap 风格（OSM 数据 + Carto CDN，国内可达；
    #    tile.openstreetmap.org 在国内被墙，所以走 CartoDB 的镜像）
    folium.TileLayer(
        tiles="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
        attr="© OpenStreetMap contributors © CARTO",
        name="🌍 OpenStreetMap",
        max_zoom=19,
        subdomains="abcd",
        show=overseas,
    ).add_to(m)

    # 3. Carto Voyager 彩色淡底（全球）
    folium.TileLayer(
        tiles="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png",
        attr="© Carto / OSM",
        name="🎨 Carto 淡彩",
        max_zoom=19,
        subdomains="abcd",
        show=False,
    ).add_to(m)

    # 4. 卫星图（ESRI World Imagery，全球可达；高德 webst01 在部分网络下被拒）
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles © Esri — Source: Esri, Maxar, Earthstar Geographics",
        name="🛰 卫星图",
        max_zoom=19,
        show=False,
    ).add_to(m)

    # 4b. 卫星图上的路名 / 地名标签（透明叠加层；用户切到卫星图时打开会更直观）
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
        attr="Labels © Esri",
        name="🏷 卫星图标签",
        max_zoom=19,
        show=False,
        overlay=True,
    ).add_to(m)

    # 按天分组
    by_day: Dict[int, List[Dict]] = {}
    for p in points:
        by_day.setdefault(p["day"], []).append(p)

    # ---------- 路线（同一天内：双层；跨天连线：灰色虚线 + 交通方式标签） ----------
    # 先把"每天的 stops 列表"按天号排序，方便后面跨天连接
    sorted_days = sorted(by_day.keys())
    day_stop_lists = [by_day[d] for d in sorted_days]

    # 同一天的彩色双层路线 —— 优先使用 OSRM 真实路网，失败回退直线
    # 假定 plan 里 lat/lng 是 GCJ-02（高德底图原生），先转 WGS-84 喂给 OSRM
    for day in sorted_days:
        stops = by_day[day]
        color = DAY_COLORS[(day - 1) % len(DAY_COLORS)]
        if len(stops) < 2:
            continue

        # 1) 直接连接（直线）的兜底坐标
        direct_coords = [[s["lat"], s["lng"]] for s in stops]

        # 2) 喂给 OSRM 的 WGS-84 坐标
        wgs_coords = [gcj02_to_wgs84(s["lat"], s["lng"]) for s in stops]
        road = fetch_road_polyline(wgs_coords, profile="driving")

        if road:
            # OSRM 返回的是 WGS-84，每个点再转回 GCJ-02 给高德底图
            coords = [list(wgs84_to_gcj02(la, ln)) for la, ln in road]
            logger.info("第%d天路网命中 %d 个折点", day, len(coords))
        else:
            coords = direct_coords

        folium.PolyLine(coords, color="#ffffff", weight=10, opacity=0.95).add_to(m)
        folium.PolyLine(coords, color=color, weight=6, opacity=0.95,
                        tooltip=f"第{day}天路线").add_to(m)

    # 跨天连线（用第 N+1 天首站的 transport 字段作为标注）
    for i in range(len(sorted_days) - 1):
        last  = day_stop_lists[i][-1]
        first = day_stop_lists[i + 1][0]
        mid_lat = (last["lat"] + first["lat"]) / 2
        mid_lng = (last["lng"] + first["lng"]) / 2
        coords = [[last["lat"], last["lng"]], [first["lat"], first["lng"]]]

        # 灰色阴影底
        folium.PolyLine(coords, color="#ffffff", weight=8, opacity=0.9).add_to(m)
        # 深灰虚线
        folium.PolyLine(coords, color="#6B5A47", weight=4, opacity=0.85,
                        dash_array="10,8",
                        tooltip=f"第{sorted_days[i]}天 → 第{sorted_days[i+1]}天"
                        ).add_to(m)

        # 交通方式取下一天首站的 transport
        transport = (first.get("transport") or "").strip()
        # 简化文字：截断到第一个"+"或"，"前
        short = transport
        for sep in (" + ", "+", "，", ","):
            if sep in short:
                short = short.split(sep)[0].strip()
                break
        if not short:
            short = "🚇 交通"

        # 按交通模式：emoji + 文字颜色
        if "高铁" in short or "动车" in short:
            icon, color = "🚄", "#E5694A"
        elif "飞机" in short or "航班" in short:
            icon, color = "✈️", "#3FA6E0"
        elif "地铁" in short:
            icon, color = "🚇", "#9C7BD9"
        elif "公交" in short or "巴士" in short:
            icon, color = "🚌", "#4FB3A9"
        elif "步行" in short:
            icon, color = "🚶", "#7CB05A"
        elif "船" in short or "渡轮" in short:
            icon, color = "🚢", "#3FA6E0"
        elif "打车" in short or "出租" in short or "网约车" in short:
            icon, color = "🚕", "#F5C84B"
        else:
            icon, color = "🚆", "#6B5A47"

        # 中点标签：去掉方框，只用粗体彩色文字 + emoji，白色描边让任何瓦片底都能看清
        label_html = f"""
        <div style="
            transform:translate(-50%,-50%);
            font-family:'PingFang SC','Microsoft YaHei',sans-serif;
            font-weight:800;font-size:13px;
            color:{color};
            text-shadow:
              -1.5px -1.5px 0 #fff, 1.5px -1.5px 0 #fff,
              -1.5px  1.5px 0 #fff, 1.5px  1.5px 0 #fff,
              0 0 6px #fff;
            white-space:nowrap;
            pointer-events:none;
            letter-spacing:0.5px;
            ">
          <span style="font-size:16px;filter:drop-shadow(0 1px 0 #fff);">{icon}</span>
          {short}
        </div>
        """
        folium.Marker(
            [mid_lat, mid_lng],
            icon=folium.DivIcon(html=label_html, icon_size=(160, 22), icon_anchor=(80, 11)),
            tooltip=f"第{sorted_days[i]}天 → 第{sorted_days[i+1]}天 · {transport or '交通方式'}",
        ).add_to(m)

    # ---------- 站点：emoji 大圆 + 永久显示地名标签 ----------
    for day, stops in sorted(by_day.items()):
        color = DAY_COLORS[(day - 1) % len(DAY_COLORS)]
        for idx, s in enumerate(stops, start=1):
            emoji = s.get("emoji") or _emoji_by_type(s.get("type") or "", s)
            place = s.get("place") or ""
            stype = s.get("type") or ""
            activities = "、".join(s.get("activities") or [])
            transport = s.get("transport") or ""
            tip = s.get("tip") or ""
            reason = s.get("reason") or ""
            scores = s.get("scores") or s.get("score") or {}
            avoid_flag = (s.get("polarity") == "avoid") or bool(s.get("avoid"))

            ring = "#C0392B" if avoid_flag else color
            inner_bg = "#FFE0DC" if avoid_flag else "#FFF8E7"
            label_color = "#C0392B" if avoid_flag else "#3B3024"

            # marker HTML：emoji 圆贴纸 + 名称标签
            # 点击向父页发 postMessage → 右栏滚到对应 stop
            marker_html = f"""
            <div class="poi-mk" data-day="{day}" data-idx="{idx}"
                onclick="window.parent.postMessage({{type:'focus-stop',day:{day},idx:{idx}}},'*');"
                style="
                text-align:center;
                font-family:'PingFang SC','Microsoft YaHei',sans-serif;
                pointer-events:auto;cursor:pointer;">
              <div style="
                  width:46px;height:46px;border-radius:50%;
                  background:{inner_bg};border:3px solid {ring};
                  box-shadow: 0 3px 0 rgba(43,33,24,0.22), 0 0 0 2.5px #FFF8E7 inset;
                  display:flex;align-items:center;justify-content:center;
                  font-size:22px;line-height:1;margin:0 auto;
                  position:relative;">
                <span style="position:absolute;top:-6px;right:-6px;
                             width:20px;height:20px;border-radius:50%;
                             background:{ring};color:#fff;border:1.6px solid #2B2118;
                             font-size:10.5px;font-weight:800;line-height:17px;">{idx}</span>
                {emoji}
              </div>
              <div style="
                  display:inline-block;background:#FFF8E7;
                  color:{label_color};border:1.6px solid #2B2118;
                  font-weight:800;font-size:11.5px;
                  padding:2px 9px;border-radius:10px 14px 10px 12px;
                  box-shadow:2px 2.5px 0 rgba(43,33,24,0.20);
                  margin-top:4px;white-space:nowrap;max-width:160px;
                  overflow:hidden;text-overflow:ellipsis;
                  {'text-decoration:line-through;' if avoid_flag else ''}">
                {place}
              </div>
            </div>
            """

            type_chip = (f"<span style='display:inline-block;background:#FFF1B5;"
                         f"border:1.5px solid #2B2118;font-size:10.5px;padding:0 7px;"
                         f"border-radius:8px;margin-left:4px;color:#3B3024;'>"
                         f"{stype}</span>" if stype else "")
            transport_html = (f"<div style='font-size:12px;color:#555;margin-top:2px;'>"
                              f"🚇 {transport}</div>" if transport else "")
            reason_html = (f"<div style='background:#EAF4FF;padding:6px 8px;"
                           f"border-radius:6px;font-size:12px;margin-top:4px;color:#1f4e79;'>"
                           f"🧭 {reason}</div>" if reason else "")
            score_html = ""
            if scores:
                score_html = (
                    f"<div style='margin:4px 0;font-size:12px;color:#444;'>"
                    f"📊 值得 <b>{scores.get('value','-')}</b> · "
                    f"上镜 <b>{scores.get('photo','-')}</b> · "
                    f"人挤 <b>{scores.get('crowded', scores.get('crowd','-'))}</b> · "
                    f"可达 <b>{scores.get('accessibility','-')}</b></div>"
                )
            tip_html = (f"<div style='background:#fff3cd;padding:6px 8px;border-radius:6px;"
                        f"font-size:12px;margin-top:4px;'>💡 {tip}</div>" if tip else "")

            popup_html = f"""
            <div style="font-family:'PingFang SC','Microsoft YaHei',sans-serif;max-width:300px;">
              <div style="font-size:16px;font-weight:800;margin-bottom:4px;">
                {emoji} {place}{type_chip}
              </div>
              <div style="font-size:11px;color:#888;margin-bottom:6px;">
                <span style="background:{ring};color:#fff;padding:1px 8px;border-radius:8px;font-weight:700;">
                  第{day}天 · 第{idx}站</span>
                {' &nbsp;<span style="color:#C0392B;font-weight:700;">⚠️ 避雷</span>' if avoid_flag else ''}
              </div>
              <div style="font-size:13px;margin-bottom:4px;">🎯 {activities}</div>
              <div style="font-size:12px;color:#666;">⏱ {s.get('time_hours','-')}h · 💰 ¥{s.get('cost','-')}</div>
              {transport_html}{score_html}{reason_html}{tip_html}
            </div>
            """

            folium.Marker(
                [s["lat"], s["lng"]],
                popup=folium.Popup(popup_html, max_width=340),
                tooltip=place,
                # 圆心落在 lat/lng；圆 46px，下方 ~26px 标签，整体高约 78px
                icon=folium.DivIcon(html=marker_html,
                                    icon_size=(180, 78), icon_anchor=(90, 23)),
            ).add_to(m)

    # 不在地图上添加任何装饰按钮 / 风格切换器
    # 用 folium 默认的 LayerControl 提供底图切换（右上角小图标）
    folium.LayerControl(position='topright', collapsed=True).add_to(m)

    overlay = """
    <style>
      .leaflet-container { background:#F0EBDA !important;
        font-family:'PingFang SC','Microsoft YaHei',sans-serif; }
      .leaflet-popup-content-wrapper { background:#FFF8E7;border:2px solid #2B2118;
        border-radius:14px;box-shadow:4px 5px 0 rgba(43,33,24,0.18); }
      .leaflet-popup-tip { background:#FFF8E7;border:2px solid #2B2118; }
      .leaflet-marker-icon { overflow:visible !important; background:transparent !important;
        border:0 !important; }
      /* LayerControl 美化（贴合手绘风） */
      .leaflet-control-layers {
        background:#FFF8E7 !important;
        border:1.8px solid #2B2118 !important;
        box-shadow:3px 3px 0 rgba(43,33,24,0.18) !important;
        border-radius:12px !important;
        font-family:'PingFang SC','Microsoft YaHei',sans-serif !important;
      }
      .leaflet-control-layers-toggle {
        background-color:#FFF8E7 !important;
        background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'><path d='M12 2 L4 6 L12 10 L20 6 Z M4 12 L12 16 L20 12 M4 18 L12 22 L20 18' fill='none' stroke='%232B2118' stroke-width='2' stroke-linejoin='round'/></svg>') !important;
        background-size:22px 22px !important;
        background-position:center !important;
        background-repeat:no-repeat !important;
      }
      .leaflet-control-layers-list label {
        font-size:13px !important;font-weight:600 !important;
        color:#3B3024 !important;margin:4px 0 !important;
      }
    </style>
    """
    m.get_root().html.add_child(folium.Element(overlay))
    return m.get_root().render()


# 类型 → emoji 的兜底映射
_TYPE_EMOJI = [
    (("景点","景区","公园","自然"), "🏞"),
    (("美食","餐饮","吃"), "🍜"),
    (("购物","商场"), "🛍"),
    (("住宿","酒店"), "🏨"),
    (("交通"), "🚆"),
    (("夜景","夜生活"), "🌃"),
    (("文化","寺庙","神社"), "⛩"),
    (("博物馆"), "🏛"),
    (("休闲","咖啡"), "☕"),
    (("体验","乐园","主题"), "🎢"),
]
def _emoji_by_type(t: str, stop: Dict) -> str:
    if not isinstance(t, str): t = str(t)
    for keys, e in _TYPE_EMOJI:
        if isinstance(keys, tuple):
            if any(k in t for k in keys):
                return e
        else:
            if keys in t:
                return e
    if (stop.get("recommended_foods") or []):
        return "🍜"
    return "📍"


def _empty_map_html(plan: Dict) -> str:
    title = plan.get("title", "旅行攻略")
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>{title}</title>
<style>html,body{{margin:0;height:100%;background:#F0EBDA;display:flex;
align-items:center;justify-content:center;font-family:'PingFang SC',sans-serif;}}
.box{{text-align:center;padding:40px;}} .big{{font-size:80px;opacity:.4}}
.ttl{{font-family:'Comic Sans MS',cursive;font-size:22px;margin-top:6px;}}
.sub{{color:#6B5A47;font-size:13px;margin-top:4px;}}
</style></head><body><div class="box">
<div class="big">🗺</div><div class="ttl">{title}</div>
<div class="sub">⚠️ 当前没有可绘制的坐标</div></div></body></html>"""
