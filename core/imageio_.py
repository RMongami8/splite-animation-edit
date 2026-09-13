"""画像I/Oユーティリティ。PNGの読み書きをストレートアルファ・uint8・sRGBで統一する
（プラン §0-7 準拠。プリマルチプライにしない）。

モジュール名の末尾に "_" を付けているのは標準ライブラリ的な imageio と名前が
衝突しないようにするため（imageio パッケージそのものは使わない）。
"""
from pathlib import Path

import numpy as np
from PIL import Image


def load_rgba(path: Path) -> np.ndarray:
    """PNG等を読み込み、ストレートアルファの uint8 RGBA (H,W,4) にして返す。"""
    img = Image.open(path)
    img = img.convert("RGBA")
    return np.array(img, dtype=np.uint8)


def load_rgb(path: Path) -> np.ndarray:
    """アルファ無視で uint8 RGB (H,W,3) を返す。"""
    img = Image.open(path).convert("RGB")
    return np.array(img, dtype=np.uint8)


def save_png(path: Path, rgba: np.ndarray) -> None:
    """uint8 RGBA (H,W,4) を PNG として保存する。ストレートアルファのまま書く。"""
    if rgba.dtype != np.uint8:
        raise ValueError(f"rgba must be uint8, got {rgba.dtype}")
    if rgba.ndim != 3 or rgba.shape[2] != 4:
        raise ValueError(f"rgba must be shape (H,W,4), got {rgba.shape}")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, mode="RGBA").save(path, format="PNG")


def probe_size(path: Path) -> tuple[int, int]:
    """(width, height) をデコードして確認する（拡張子だけで判定しない）。"""
    with Image.open(path) as img:
        return img.size
