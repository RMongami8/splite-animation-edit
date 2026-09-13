"""キーフレーム抽出の補助(レイヤー追加ウィザード用)。numpy/Pillow のみ。

ここはスコア計算だけを持つ。しきい値による採否はフロント(layerwizard.js)が
スライダー操作に合わせて即時に行う。
"""
from pathlib import Path

import numpy as np
from PIL import Image


def _small_rgba(path: Path, size: int) -> np.ndarray:
    with Image.open(path) as im:
        im = im.convert("RGBA").resize((size, size), Image.BOX)
        return np.asarray(im, dtype=np.float32) / 255.0


def frame_diff_scores(paths: list[Path], size: int = 48) -> list[float]:
    """各フレームと直前フレームの平均絶対差(0-1)。先頭は 1.0(必ず採用候補)。"""
    scores: list[float] = []
    prev = None
    for p in paths:
        cur = _small_rgba(p, size)
        if prev is None:
            scores.append(1.0)
        else:
            scores.append(float(np.abs(cur - prev).mean()))
        prev = cur
    return scores
