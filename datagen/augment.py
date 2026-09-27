"""Augmentation 3 mức (spec mục 5): clean (render gốc), scan, photo.

scan : xoay ±3°, nhiễu, giảm tương phản, JPEG chất lượng 60
photo: đặt lên nền bàn, méo phối cảnh, bóng đổ, mờ, lệch sáng, JPEG chất lượng 75
"""

from __future__ import annotations

import random

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

LEVELS = ("clean", "scan", "photo")
JPEG_QUALITY = {"clean": 95, "scan": 60, "photo": 75}


def _noise(img: Image.Image, sigma: float, nrng: np.random.Generator) -> Image.Image:
    a = np.asarray(img, dtype=np.float32)
    a = a + nrng.normal(0, sigma, a.shape[:2])[..., None]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def _perspective_coeffs(dst: list[tuple[float, float]], src: list[tuple[float, float]]) -> list[float]:
    """Hệ số cho Image.transform(PERSPECTIVE): ánh xạ điểm ảnh ra (dst) -> điểm ảnh vào (src)."""
    rows, rhs = [], []
    for (x, y), (u, v) in zip(dst, src):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        rhs += [u, v]
    return np.linalg.solve(np.array(rows, float), np.array(rhs, float)).tolist()


def _scan(img: Image.Image, rng: random.Random, nrng: np.random.Generator) -> Image.Image:
    img = img.rotate(rng.uniform(-3, 3), resample=Image.BICUBIC, expand=True, fillcolor=(238, 238, 232))
    img = ImageEnhance.Contrast(img).enhance(rng.uniform(0.75, 0.92))
    img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 0.8)))
    return _noise(img, rng.uniform(6, 12), nrng)


def _photo(img: Image.Image, rng: random.Random, nrng: np.random.Generator) -> Image.Image:
    w, h = img.size
    pad = int(0.06 * max(w, h))
    table = tuple(rng.randint(90, 150) for _ in range(3))
    canvas = Image.new("RGB", (w + 2 * pad, h + 2 * pad), table)
    canvas.paste(img, (pad, pad))
    W, H = canvas.size
    j = 0.05
    dst = [(0, 0), (W, 0), (W, H), (0, H)]
    src = [(x + rng.uniform(-j, j) * W, y + rng.uniform(-j, j) * H) for x, y in dst]
    canvas = canvas.transform((W, H), Image.PERSPECTIVE, _perspective_coeffs(dst, src),
                              resample=Image.BICUBIC, fillcolor=table)
    # bóng đổ: gradient tuyến tính theo hướng ngẫu nhiên
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    ang = rng.uniform(0, 2 * np.pi)
    g = (xx * np.cos(ang) + yy * np.sin(ang))
    g = (g - g.min()) / (g.max() - g.min())
    shade = 1 - rng.uniform(0.25, 0.45) * np.clip(g - rng.uniform(0.3, 0.6), 0, 1) / 0.5
    a = np.asarray(canvas, dtype=np.float32) * shade[..., None]
    canvas = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    canvas = ImageEnhance.Brightness(canvas).enhance(rng.uniform(0.85, 1.05))
    canvas = canvas.filter(ImageFilter.GaussianBlur(rng.uniform(0.8, 1.6)))
    return _noise(canvas, rng.uniform(3, 6), nrng)


def augment(img: Image.Image, level: str, rng: random.Random) -> Image.Image:
    nrng = np.random.default_rng(rng.getrandbits(32))
    if level == "clean":
        return img
    return _scan(img, rng, nrng) if level == "scan" else _photo(img, rng, nrng)
