"""
Weather service — lấy thời tiết từ OpenWeatherMap (free tier).
Cache 3 giờ trong DB để tiết kiệm API calls.
"""

import logging
from datetime import datetime, timedelta

import httpx

from app.config import OPENWEATHER_API_KEY

log = logging.getLogger(__name__)

WEATHER_ENABLED = bool(OPENWEATHER_API_KEY)

# Tọa độ đại diện cho từng vùng nông nghiệp
REGION_COORDS: dict[str, tuple[float, float]] = {
    "mekong":    (10.0452, 105.7469),   # Cần Thơ — Đồng bằng Sông Cửu Long
    "southeast": (11.0686, 106.6148),   # TP.HCM — Đông Nam Bộ
    "central_highland": (11.9465, 108.4419),  # Đà Lạt — Tây Nguyên
    "south_central": (13.0827, 109.0967),     # Quy Nhơn — Duyên hải Nam Trung Bộ
    "north_central": (17.4673, 106.6221),     # Đồng Hới — Bắc Trung Bộ
    "red_river": (20.9714, 105.7877),   # Hà Nội — Đồng bằng Sông Hồng
    "northeast":  (21.8227, 106.7615),  # Lạng Sơn — Trung du Bắc Bộ
    "northwest":  (22.3964, 103.8316),  # Lào Cai — Tây Bắc
}

REGION_NAMES: dict[str, str] = {
    "mekong":           "Đồng bằng Sông Cửu Long",
    "southeast":        "Đông Nam Bộ",
    "central_highland": "Tây Nguyên",
    "south_central":    "Duyên hải Nam Trung Bộ",
    "north_central":    "Bắc Trung Bộ",
    "red_river":        "Đồng bằng Sông Hồng",
    "northeast":        "Trung du & Miền núi Bắc Bộ",
    "northwest":        "Tây Bắc",
}

# Dịch condition sang tiếng Việt
_CONDITION_MAP = {
    "clear sky": "trời quang",
    "few clouds": "ít mây",
    "scattered clouds": "có mây",
    "broken clouds": "nhiều mây",
    "overcast clouds": "trời âm u",
    "light rain": "mưa nhỏ",
    "moderate rain": "mưa vừa",
    "heavy intensity rain": "mưa to",
    "very heavy rain": "mưa rất to",
    "thunderstorm": "có giông",
    "drizzle": "mưa phùn",
    "mist": "sương mù",
    "fog": "sương mù dày",
    "haze": "trời mờ",
}


def _vi_condition(desc: str) -> str:
    return _CONDITION_MAP.get(desc.lower(), desc)


async def get_weather(region: str = "", lat: float = 0.0, lon: float = 0.0) -> str:
    """
    Trả về chuỗi mô tả thời tiết (vd: "32°C, mưa nhỏ, độ ẩm 85%").
    Ưu tiên lat/lon nếu có, ngược lại tra từ region.
    Trả về "" nếu không lấy được.
    """
    if not WEATHER_ENABLED:
        return ""

    # Xác định tọa độ
    if not (lat and lon) and region in REGION_COORDS:
        lat, lon = REGION_COORDS[region]
    if not (lat and lon):
        return ""

    # Kiểm tra cache
    cached = _get_cache(lat, lon)
    if cached:
        return cached

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={
                    "lat": lat, "lon": lon,
                    "appid": OPENWEATHER_API_KEY,
                    "units": "metric",
                    "lang": "en",
                },
            )
            res.raise_for_status()
            data = res.json()

        temp     = round(data["main"]["temp"])
        humidity = data["main"]["humidity"]
        desc     = data["weather"][0]["description"]
        result   = f"{temp}°C, {_vi_condition(desc)}, độ ẩm {humidity}%"
        _set_cache(lat, lon, result)
        return result
    except Exception as e:
        log.warning("Weather API lỗi: %s", e)
        return ""


# ---------------------------------------------------------------------------
# In-memory cache đơn giản (key = rounded lat/lon, TTL = 3 giờ)
# ---------------------------------------------------------------------------

_weather_cache: dict[str, tuple[str, datetime]] = {}
_CACHE_TTL_HOURS = 3


def _cache_key(lat: float, lon: float) -> str:
    return f"{round(lat, 2)},{round(lon, 2)}"


def _get_cache(lat: float, lon: float) -> str:
    key = _cache_key(lat, lon)
    entry = _weather_cache.get(key)
    if entry and datetime.now() - entry[1] < timedelta(hours=_CACHE_TTL_HOURS):
        return entry[0]
    return ""


def _set_cache(lat: float, lon: float, value: str) -> None:
    _weather_cache[_cache_key(lat, lon)] = (value, datetime.now())
