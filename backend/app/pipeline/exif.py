"""EXIF GPS 直读：优先 exifread（纯 Python、容错好），PIL 兜底。

注意：手机厂商常把 GPS 写入 XMP 而非标准 EXIF，此模块先覆盖标准 EXIF；
XMP 解析留作 TODO（Phase 3）。
"""
from __future__ import annotations

import io
from typing import Optional

from ..schemas import GPSCoord

_DMS_KEYS = {
    "lat": ("GPSLatitude", "GPSLatitudeRef"),
    "lon": ("GPSLongitude", "GPSLongitudeRef"),
}


def _dms_to_decimal(dms, ref: str) -> float:
    """(deg, min, sec) 元组 → 十进制度数。"""
    deg, min_, sec = (float(x.num) / float(x.den) for x in dms)
    value = deg + min_ / 60.0 + sec / 3600.0
    if ref in ("S", "W"):
        value = -value
    return value


def extract_gps_exifread(data: bytes) -> Optional[GPSCoord]:
    import exifread

    tags = exifread.process_file(io.BytesIO(data), details=False)
    if "GPS GPSLatitude" not in tags or "GPS GPSLongitude" not in tags:
        return None

    lat = _dms_to_decimal(tags["GPS GPSLatitude"].values, str(tags["GPS GPSLatitudeRef"]))
    lon = _dms_to_decimal(tags["GPS GPSLongitude"].values, str(tags["GPS GPSLongitudeRef"]))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None

    altitude = None
    if "GPS GPSAltitude" in tags:
        try:
            alt = tags["GPS GPSAltitude"].values[0]
            altitude = float(alt.num) / float(alt.den)
        except Exception:
            altitude = None

    captured_at = None
    for key in ("EXIF DateTimeOriginal", "Image DateTime", "EXIF DateTimeDigitized"):
        if key in tags:
            captured_at = str(tags[key])
            break

    return GPSCoord(lat=round(lat, 7), lon=round(lon, 7), altitude_m=altitude,
                    source="exif", captured_at=captured_at)


def extract_gps_pil(data: bytes) -> Optional[GPSCoord]:
    """PIL 兜底（标准 EXIF GPS）。"""
    try:
        from PIL import Image, ExifTags
        from PIL.ExifTags import GPSTAGS

        img = Image.open(io.BytesIO(data))
        exif = img.getexif()
        if exif is None:
            return None
        gps_ifd = exif.get_ifd(ExifTags.IFD.GPSInfo)
        if not gps_ifd:
            return None
        gps = {GPSTAGS.get(k, k): v for k, v in gps_ifd.items()}
        if "GPSLatitude" not in gps or "GPSLongitude" not in gps:
            return None

        def _conv(val):
            d, m, s = val
            return float(d) + float(m) / 60.0 + float(s) / 3600.0

        lat = _conv(gps["GPSLatitude"])
        lon = _conv(gps["GPSLongitude"])
        if gps.get("GPSLatitudeRef") == "S":
            lat = -lat
        if gps.get("GPSLongitudeRef") == "W":
            lon = -lon
        return GPSCoord(lat=round(lat, 7), lon=round(lon, 7), source="exif")
    except Exception:
        return None


def extract_gps(data: bytes) -> Optional[GPSCoord]:
    """主入口：exifread 优先，PIL 兜底。"""
    gps = extract_gps_exifread(data)
    if gps:
        return gps
    return extract_gps_pil(data)


def extract_captured(data: bytes) -> Optional[str]:
    """提取拍摄时间（B3 昼夜校验用）。"""
    try:
        import exifread
        tags = exifread.process_file(io.BytesIO(data), details=False)
        for key in ("EXIF DateTimeOriginal", "Image DateTime", "EXIF DateTimeDigitized"):
            if key in tags:
                return str(tags[key])
    except Exception:
        pass
    return None
