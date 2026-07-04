"""Ucuz piksel-diff ön filtresi (ARCHITECTURE.md §3.2).

Vision modeline gitmeden önce screenshot ile referans mockup arasındaki kaba
farkı ölçer; fark eşiğin altındaysa LLM çağrısı atlanır (maliyet optimizasyonu).
"""

from __future__ import annotations

import io


def pixel_diff_ratio(png_a: bytes, png_b: bytes) -> float:
    """0.0 (aynı) .. 1.0 (tamamen farklı). Pillow yoksa 1.0 (LLM'e gönder)."""
    try:
        from PIL import Image
    except ImportError:
        return 1.0

    a = Image.open(io.BytesIO(png_a)).convert("L").resize((64, 128))
    b = Image.open(io.BytesIO(png_b)).convert("L").resize((64, 128))
    pa, pb = a.tobytes(), b.tobytes()
    diff = sum(abs(x - y) for x, y in zip(pa, pb))
    return diff / (len(pa) * 255)
