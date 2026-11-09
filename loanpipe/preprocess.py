"""Bước 2: xoay thẳng ảnh trước khi đưa cho VLM. Bật bằng VLM_PREPROCESS=deskew, mặc định tắt.

Tắt để số liệu đã công bố tái lập được từ cache, và vì chưa đo được lợi ích trên dev.
ponytail: chỉ xử lý góc xoay; méo phối cảnh của ảnh chụp cần tìm 4 góc giấy, thêm khi đo thấy cần.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter, ImageOps

MAX_ANGLE = 5.0     # scan trong spec lệch tối đa 3°; ngoài khoảng này không tự xoay
MIN_ANGLE = 0.3     # lệch nhỏ hơn thì giữ nguyên ảnh, tránh nội suy làm mờ chữ vô ích
MIN_GAIN = 1.05     # góc tốt nhất phải rõ hơn góc 0; ảnh ít dòng chữ thì không đoán


def _ink(img: Image.Image, side: int = 800) -> Image.Image:
    """Mặt nạ nét chữ. So với nền cục bộ để bóng đổ trên ảnh chụp không bị tính là chữ."""
    g = ImageOps.grayscale(img)
    g.thumbnail((side, side))
    a = np.asarray(g, dtype=np.int16)
    background = np.asarray(g.filter(ImageFilter.BoxBlur(12)), dtype=np.int16)
    return Image.fromarray(((background - a > 18) * 255).astype(np.uint8))


def _score(ink: Image.Image, angle: float) -> float:
    """Dòng chữ nằm ngang thì tổng theo hàng đổi đột ngột giữa dòng chữ và khoảng trắng."""
    rows = np.asarray(ink.rotate(angle, resample=Image.NEAREST), dtype=np.float64).sum(axis=1)
    return float((np.diff(rows) ** 2).sum())


def estimate_skew(img: Image.Image) -> float:
    """Góc cần truyền cho Image.rotate để dòng chữ nằm ngang; 0 nếu không đủ chắc."""
    ink = _ink(img)
    base = _score(ink, 0)
    if base == 0:
        return 0.0
    coarse = max(np.arange(-MAX_ANGLE, MAX_ANGLE + 0.01, 0.5), key=lambda a: _score(ink, a))
    best = max(np.arange(coarse - 0.4, coarse + 0.41, 0.1), key=lambda a: _score(ink, a))
    if abs(best) < MIN_ANGLE or _score(ink, best) < base * MIN_GAIN:
        return 0.0
    return round(float(best), 1)


def deskew(img: Image.Image) -> Image.Image:
    angle = estimate_skew(img)
    if not angle:
        return img
    corner = img.convert("RGB").getpixel((0, 0))
    return img.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=corner)
