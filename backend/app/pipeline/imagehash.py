"""图片感知哈希（dHash）：重复图片识别 → 结果缓存。"""
from __future__ import annotations

import hashlib
import io

from PIL import Image, ImageOps


def image_dhash(data: bytes) -> str:
    """dHash：灰度 → 9x8 → 相邻像素差分 → 64bit 十六进制。"""
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.grayscale(img)
        img = img.resize((9, 8), Image.LANCZOS)
        bits = []
        px = img.load()
        for y in range(8):
            for x in range(8):
                bits.append("1" if px[x, y] > px[x + 1, y] else "0")
        return hex(int("".join(bits), 2))[2:].zfill(16)
    except Exception:
        # 无法解析的图片：退回内容哈希（保证同一字节流仍可命中）
        return hashlib.sha256(data).hexdigest()[:16]
