import math
import xml.etree.ElementTree as ET
from pathlib import Path


def _haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius * c


def _smooth_series(values: list[float], window: int = 1) -> list[float]:
    if window <= 0 or len(values) <= 2:
        return values[:]
    smoothed: list[float] = []
    size = len(values)
    for index in range(size):
        start = max(0, index - window)
        end = min(size, index + window + 1)
        smoothed.append(sum(values[start:end]) / float(end - start))
    return smoothed


def _downsample_profile(profile: list[dict], max_points: int = 500) -> list[dict]:
    if len(profile) <= max_points:
        return profile
    step = max(1, math.ceil(len(profile) / max_points))
    sampled = [profile[index] for index in range(0, len(profile), step)]
    if sampled[-1] != profile[-1]:
        sampled.append(profile[-1])
    return sampled


def _waypoint_kind(name: str, waypoint_type: str, symbol: str, comment: str, desc: str) -> str:
    merged = " ".join([name, waypoint_type, symbol, comment, desc]).lower()
    raw_type = _normalize_text(waypoint_type)
    if raw_type in {"high", "medium", "low", "risk", "风险", "高风险", "中风险", "低风险"}:
        return "risk"
    if raw_type.startswith("risk:") or raw_type.startswith("risk-") or raw_type.startswith("risk_"):
        return "risk"
    risk_keywords = (
        "risk",
        "danger",
        "restricted",
        "construction",
        "warning",
        "危险",
        "施工",
        "管制",
        "绕行",
        "封闭",
        "注意",
        "下坡",
        "急弯",
    )
    supply_keywords = (
        "supply",
        "shop",
        "store",
        "water",
        "food",
        "rest",
        "toilet",
        "补给",
        "便利店",
        "加油站",
        "饮水",
        "卫生间",
        "休息",
    )
    if any(keyword in merged for keyword in risk_keywords):
        return "risk"
    if any(keyword in merged for keyword in supply_keywords):
        return "supply"
    return "poi"


def _normalize_text(value: str) -> str:
    return (value or "").strip().lower()


def _risk_level_from_type(waypoint_type: str) -> str | None:
    raw_type = _normalize_text(waypoint_type)
    if not raw_type:
        return None
    if raw_type in {"high", "risk:high", "risk-high", "risk_high", "高", "高风险"}:
        return "high"
    if raw_type in {"medium", "risk:medium", "risk-medium", "risk_mid", "risk_medium", "中", "中风险"}:
        return "medium"
    if raw_type in {"low", "risk:low", "risk-low", "risk_low", "低", "低风险"}:
        return "low"
    if raw_type.endswith(":high") or raw_type.endswith("-high") or raw_type.endswith("_high"):
        return "high"
    if raw_type.endswith(":medium") or raw_type.endswith("-medium") or raw_type.endswith("_medium"):
        return "medium"
    if raw_type.endswith(":low") or raw_type.endswith("-low") or raw_type.endswith("_low"):
        return "low"
    return None


def _waypoint_risk_level(waypoint_type: str, symbol: str, comment: str, desc: str, kind: str) -> str | None:
    if kind != "risk":
        return None

    direct_level = _risk_level_from_type(waypoint_type)
    if direct_level:
        return direct_level

    merged = " ".join([waypoint_type, symbol, comment, desc]).lower()
    if any(keyword in merged for keyword in ("高风险", "严重", "危险", "管制", "封闭", "restricted", "danger")):
        return "high"
    if any(keyword in merged for keyword in ("低风险", "注意", "减速", "caution")):
        return "low"
    return "medium"


def parse_gpx_waypoints(file_path: Path) -> list[dict]:
    tree = ET.parse(file_path)
    root = tree.getroot()
    waypoints: list[dict] = []
    for node in root.findall(".//{*}wpt"):
        lat_raw = node.attrib.get("lat")
        lon_raw = node.attrib.get("lon")
        if lat_raw is None or lon_raw is None:
            continue
        try:
            lat = float(lat_raw)
            lon = float(lon_raw)
        except ValueError:
            continue
        name = (node.findtext("{*}name") or "").strip()
        comment = (node.findtext("{*}cmt") or "").strip()
        desc = (node.findtext("{*}desc") or "").strip()
        symbol = (node.findtext("{*}sym") or "").strip()
        waypoint_type = (node.findtext("{*}type") or "").strip()
        kind = _waypoint_kind(name, waypoint_type, symbol, comment, desc)
        waypoints.append(
            {
                "lat": lat,
                "lon": lon,
                "name": name,
                "comment": comment,
                "desc": desc,
                "symbol": symbol,
                "type": waypoint_type,
                "kind": kind,
                "risk_level": _waypoint_risk_level(waypoint_type, symbol, comment, desc, kind),
            }
        )
    return waypoints


def parse_gpx_points_and_stats(file_path: Path) -> tuple[list[list[float]], dict, list[dict]]:
    tree = ET.parse(file_path)
    root = tree.getroot()

    points: list[list[float]] = []
    total_distance_m = 0.0
    total_ascent_m = 0.0
    total_descent_m = 0.0
    min_ele = None
    max_ele = None
    elevation_samples = 0
    elevation_unique_values: set[float] = set()
    elevation_values: list[float] = []
    elevation_distance_km: list[float] = []

    for segment in root.findall(".//{*}trkseg"):
        prev_lat = None
        prev_lon = None
        for node in segment.findall(".//{*}trkpt"):
            lat_raw = node.attrib.get("lat")
            lon_raw = node.attrib.get("lon")
            if lat_raw is None or lon_raw is None:
                continue
            try:
                lat = float(lat_raw)
                lon = float(lon_raw)
            except ValueError:
                continue

            points.append([lat, lon])
            if prev_lat is not None and prev_lon is not None:
                total_distance_m += _haversine_meters(prev_lat, prev_lon, lat, lon)
            prev_lat = lat
            prev_lon = lon

            ele_node = node.find("{*}ele")
            current_ele = None
            if ele_node is not None and ele_node.text is not None:
                try:
                    current_ele = float(ele_node.text.strip())
                except ValueError:
                    current_ele = None
            if current_ele is not None:
                elevation_samples += 1
                elevation_unique_values.add(round(current_ele, 2))
                elevation_values.append(current_ele)
                elevation_distance_km.append(round(total_distance_m / 1000.0, 3))
                min_ele = current_ele if min_ele is None else min(min_ele, current_ele)
                max_ele = current_ele if max_ele is None else max(max_ele, current_ele)

    has_valid_elevation = elevation_samples >= 2 and len(elevation_unique_values) > 1
    elevation_profile: list[dict] = []
    if has_valid_elevation:
        # Adaptive smoothing by elevation sample size.
        # Larger tracks usually contain more noisy zig-zag altitude jitter.
        # `sample/18` was calibrated against current GPX set to keep long routes realistic.
        smooth_window = max(1, min(30, round(elevation_samples / 18)))
        smoothed = _smooth_series(elevation_values, window=smooth_window)
        total_ascent_m = 0.0
        total_descent_m = 0.0
        for prev, curr in zip(smoothed, smoothed[1:]):
            delta = curr - prev
            if delta > 0:
                total_ascent_m += delta
            elif delta < 0:
                total_descent_m += abs(delta)
        elevation_profile = [
            {"distance_km": dist, "elevation_m": round(ele, 1)}
            for dist, ele in zip(elevation_distance_km, smoothed)
        ]
        elevation_profile = _downsample_profile(elevation_profile)
    else:
        smooth_window = 0

    stats = {
        "distance_m": round(total_distance_m, 1),
        "distance_km": round(total_distance_m / 1000.0, 2),
        "ascent_m": round(total_ascent_m, 1) if has_valid_elevation else None,
        "descent_m": round(total_descent_m, 1) if has_valid_elevation else None,
        "min_ele_m": round(min_ele, 1) if min_ele is not None else None,
        "max_ele_m": round(max_ele, 1) if max_ele is not None else None,
        "elevation_samples": elevation_samples,
        "has_valid_elevation": has_valid_elevation,
        "elevation_smoothing_window": smooth_window,
    }
    return points, stats, elevation_profile
