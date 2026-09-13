"""M0 検証用ダミー素材の生成（プラン §0-12: 64×64・8コマで検証する）。

8コマ・2レイヤー（キャラ=通常合成の不透明円、エフェクト=加算合成の発光）を作り、
Composition/Layer/Exposure を DB に直接書き込む。importers.py (M1) を経由せず、
selftest_time / selftest_roundtrip がすぐ使える固定データを用意するための
テスト専用フィクスチャ生成器。

固定ID（冪等: 再実行すると同じ ID を消してから作り直す）:
  comp_id="cp_dummy", layers=["ly_dummy_char","ly_dummy_fx"],
  assets=["as_dummy_char","as_dummy_fx"]

使い方: python -m tools.make_dummy
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from core import db, store
from core.imageio_ import save_png
from core.timeline import distribute_holds, uniform_boundaries

ROOT = Path(__file__).resolve().parent.parent
SIZE = 64
N_FRAMES = 8
TOTAL_MS = 4000

COMP_ID = "cp_dummy"
LAYER_CHAR = "ly_dummy_char"
LAYER_FX = "ly_dummy_fx"
ASSET_CHAR = "as_dummy_char"
ASSET_FX = "as_dummy_fx"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _circle_mask(size: int, cx: float, cy: float, r: float) -> np.ndarray:
    yy, xx = np.mgrid[0:size, 0:size]
    return ((xx - cx) ** 2 + (yy - cy) ** 2) <= (r * r)


def _make_char_frame(i: int) -> np.ndarray:
    """歩行を模した円が左右に揺れる、不透明キャラのRGBA(既にマット済み想定)。"""
    rgba = np.zeros((SIZE, SIZE, 4), np.uint8)
    cx = SIZE / 2 + 10 * np.sin(2 * np.pi * i / N_FRAMES)
    cy = SIZE * 0.6
    mask = _circle_mask(SIZE, cx, cy, 12)
    rgba[mask, 0] = 60 + i * 10   # フレームごとに色を変え目視で区別できるようにする
    rgba[mask, 1] = 140
    rgba[mask, 2] = 220
    rgba[mask, 3] = 255
    return rgba


def _make_fx_frame(i: int) -> np.ndarray:
    """明滅する発光ブロブのRGBA。加算合成対象なのでアルファは合成に使われない。"""
    rgba = np.zeros((SIZE, SIZE, 4), np.uint8)
    cx, cy = SIZE / 2, SIZE * 0.4
    r = 8 + 4 * (i % 4)
    mask = _circle_mask(SIZE, cx, cy, r)
    brightness = 120 + (i * 130) // N_FRAMES
    rgba[mask, 0] = min(255, brightness + 60)
    rgba[mask, 1] = min(255, brightness + 30)
    rgba[mask, 2] = min(255, brightness)
    rgba[mask, 3] = 255
    return rgba


def _wipe_existing(conn) -> None:
    conn.execute("DELETE FROM exposures WHERE layer_id IN (?, ?)", (LAYER_CHAR, LAYER_FX))
    conn.execute("DELETE FROM layers WHERE id IN (?, ?)", (LAYER_CHAR, LAYER_FX))
    conn.execute("DELETE FROM compositions WHERE id = ?", (COMP_ID,))
    conn.execute("DELETE FROM frames WHERE asset_id IN (?, ?)", (ASSET_CHAR, ASSET_FX))
    conn.execute("DELETE FROM assets WHERE id IN (?, ?)", (ASSET_CHAR, ASSET_FX))
    conn.commit()


def _make_asset(conn, asset_id: str, frame_fn, kind_label: str) -> None:
    now = _now()
    frame_dir_rel = f"derived/frames/{asset_id}"
    # frames は assets(id) を参照する外部キーを持つため、先に asset 行を作る
    conn.execute(
        "INSERT INTO assets(id, kind, rel_path, sha256, width, height, n_frames, "
        "tb_num, tb_den, rotation, has_alpha, source, attempt_id, meta_json, "
        "created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (asset_id, "sequence", frame_dir_rel, "dummy", SIZE, SIZE, N_FRAMES,
         1, N_FRAMES, 0, 1, "derived", None,
         json.dumps({"dummy": True, "label": kind_label}, ensure_ascii=False), now),
    )
    for i in range(N_FRAMES):
        rgba = frame_fn(i)
        frame_id = f"f{i:04d}"
        rel = f"{frame_dir_rel}/{frame_id}.png"
        abs_path = store.to_abs(rel)
        save_png(abs_path, rgba)
        conn.execute(
            "INSERT INTO frames(asset_id, frame_id, idx, pts, rel_path, width, "
            "height, has_alpha) VALUES (?,?,?,?,?,?,?,?)",
            (asset_id, frame_id, i, i, rel, SIZE, SIZE, 1),
        )


def _make_layer(conn, layer_id: str, asset_id: str, name: str, kind: str, blend: str, z: int) -> None:
    now = _now()
    conn.execute(
        "INSERT INTO layers(id, comp_id, name, kind, blend, opacity, z, "
        "start_ticks, after_end, visible, matte_json, anchor_json) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (layer_id, COMP_ID, name, kind, blend, 1.0, z, 0, "hold", 1, "{}", "{}"),
    )
    holds = distribute_holds(TOTAL_MS, uniform_boundaries(N_FRAMES))
    for i, hold in enumerate(holds):
        exposure_id = f"ex_dummy_{name}_{i}"
        conn.execute(
            "INSERT INTO exposures(id, layer_id, ord, asset_id, frame_id, "
            "hold_ticks, dx, dy, flip_x, matte_mode, matte_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (exposure_id, layer_id, i, asset_id, f"f{i:04d}", hold, 0, 0, 0,
             "inherit", "{}"),
        )


def run() -> dict:
    store.init(ROOT / "data")
    conn = db.connect(ROOT / "data" / "studio.db")
    with db.write_lock():
        _wipe_existing(conn)
        _make_asset(conn, ASSET_CHAR, _make_char_frame, "character")
        _make_asset(conn, ASSET_FX, _make_fx_frame, "effect")
        now = _now()
        conn.execute(
            "INSERT INTO compositions(id, name, canvas_w, canvas_h, tick_rate, "
            "total_ticks, loop, revision, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (COMP_ID, "dummy", SIZE, SIZE, 1000, TOTAL_MS, 1, 1, now, now),
        )
        _make_layer(conn, LAYER_CHAR, ASSET_CHAR, "char", "normal", "normal", 0)
        _make_layer(conn, LAYER_FX, ASSET_FX, "fx", "glow", "add", 1)
        conn.commit()
    return {
        "comp_id": COMP_ID,
        "layers": [LAYER_CHAR, LAYER_FX],
        "assets": [ASSET_CHAR, ASSET_FX],
        "n_frames": N_FRAMES,
        "total_ms": TOTAL_MS,
    }


def main() -> int:
    result = run()
    print(f"dummy composition created: comp_id={result['comp_id']} "
          f"layers={result['layers']} n_frames={result['n_frames']} "
          f"total_ms={result['total_ms']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
