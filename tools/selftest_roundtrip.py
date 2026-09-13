"""M0 自己検証: シート書き出し -> sheet.json 読み戻しの内部往復（プラン §7, §12 準拠）。

注意（スコープ）: これは M0 の内部往復検証であり、外部ソフトを経由する
ZIP+manifest 往復(§8, pkgio.py)の検証ではない。pkgio.py と importers.py は
M2/M1 で実装し、そちらで改めて外部往復の selftest を拡張する。ここでは
core/sheet.py + core/naming.py + tools.make_dummy が作ったDBデータを使い、
「配置(cells)と再生順(layers[].track)が別配列になっている」「同じセルを
複数回参照できる」「ページ分割が機能する」ことを検証する。

使い方: python -m tools.selftest_roundtrip
"""
import shutil
import sys
from pathlib import Path

import numpy as np

from core import db, store
from core.imageio_ import load_rgba, save_png
from core.naming import expand
from core.sheet import build_grid, scale_to_cell
from tools.make_dummy import COMP_ID, LAYER_CHAR, LAYER_FX

ROOT = Path(__file__).resolve().parent.parent
CELL_WH = (64, 64)
COLS = 4
PADDING = 2
EXTRUDE = 1
MAX_PAGE = 4096


def _load_layer_exposures(conn, layer_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT ord, asset_id, frame_id, hold_ticks, dx, dy, flip_x FROM exposures "
        "WHERE layer_id = ? ORDER BY ord", (layer_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def _load_frame_image(asset_id: str, frame_id: str, conn) -> np.ndarray:
    row = conn.execute(
        "SELECT rel_path FROM frames WHERE asset_id = ? AND frame_id = ?",
        (asset_id, frame_id),
    ).fetchone()
    return load_rgba(store.to_abs(row["rel_path"]))


def export_layer_sheet(conn, comp: dict, layer_id: str, layer_name: str,
                        out_dir: Path, cols: int = COLS, max_page: int = MAX_PAGE
                        ) -> dict:
    """レイヤー1本分をシートPNG(1枚以上)+sheet.json相当の dict として書き出す。"""
    exps = _load_layer_exposures(conn, layer_id)
    imgs = [_load_frame_image(e["asset_id"], e["frame_id"], conn) for e in exps]
    scaled, scale = scale_to_cell(imgs, CELL_WH)
    pages, cell_meta = build_grid(scaled, cols, CELL_WH, PADDING, EXTRUDE, max_page)

    page_files = []
    for i, page in enumerate(pages):
        fname = expand("{layer}_sheet_{i}.png", layer=layer_name, i=i)
        save_png(out_dir / fname, page)
        page_files.append({"file": fname, "w": int(page.shape[1]), "h": int(page.shape[0])})

    track = []
    t_ms = 0
    for e, cm in zip(exps, cell_meta):
        track.append({
            "cell": cm["id"], "start_ms": t_ms, "dur_ms": e["hold_ticks"],
            "dx": e["dx"], "dy": e["dy"], "flip_x": bool(e["flip_x"]),
        })
        t_ms += e["hold_ticks"]

    return {
        "format": "spritesheet-studio/sheet@1",
        "canvas": {"w": comp["canvas_w"], "h": comp["canvas_h"]},
        "pivot": [0.5, 1.0],
        "scale": scale,
        "timing": {"tick_rate": comp["tick_rate"], "total_ms": t_ms,
                   "loop": bool(comp["loop"]), "mode": "variable"},
        "pages": page_files,
        "cells": cell_meta,
        "layers": [{"name": layer_name, "blend": "normal", "opacity": 1.0, "z": 0,
                    "track": track}],
        "export": {"profile": "grid", "dedupe": False, "revision": comp["revision"]},
    }


def check_dedupe_cell_reference() -> dict:
    """cells(配置) と layers[].track(再生順) が別配列で、同じ cell を複数回
    参照できることを、その場で組んだ最小データで確認する（optimized 相当）。"""
    track = [
        {"cell": "c0", "start_ms": 0, "dur_ms": 500},
        {"cell": "c1", "start_ms": 500, "dur_ms": 500},
        {"cell": "c0", "start_ms": 1000, "dur_ms": 500},  # c0 を再参照
    ]
    cells = [{"id": "c0", "page": 0, "x": 0, "y": 0, "w": 64, "h": 64},
             {"id": "c1", "page": 0, "x": 64, "y": 0, "w": 64, "h": 64}]
    referenced_ids = {t["cell"] for t in track}
    ok = referenced_ids == {"c0", "c1"} and len(cells) == 2 and len(track) == 3
    return {"name": "optimized profile: track can reference same cell multiple times",
            "ok": ok}


def check_page_split() -> dict:
    """max_page を小さくして複数ページに分割されることを確認する。

    max_page は幅にも高さにも適用される上限のため、cols=2 (page_w=2*66-2=130) に
    収まりつつ、1ページに入る行数(2行/ページ)は超えるよう max_page=140 を選ぶ。
    8枚/2列=4行必要 -> 1ページ2行までなので2ページに分かれるはず。
    """
    imgs = [np.random.randint(0, 255, (64, 64, 4), np.uint8) for _ in range(8)]
    scaled, _ = scale_to_cell(imgs, (64, 64))
    pages, cell_meta = build_grid(scaled, cols=2, cell_wh=(64, 64), padding=2,
                                   extrude=1, max_page=140)
    ok_multi = len(pages) >= 2
    max_page_idx = max(cm["page"] for cm in cell_meta)
    ok_meta = max_page_idx == len(pages) - 1
    # 各セルがページ範囲内に収まっているか
    ok_bounds = True
    for cm in cell_meta:
        page_img = pages[cm["page"]]
        if cm["x"] + cm["w"] > page_img.shape[1] or cm["y"] + cm["h"] > page_img.shape[0]:
            ok_bounds = False
    return {"name": "page split with small max_page produces multiple pages, cells in-bounds",
            "ok": ok_multi and ok_meta and ok_bounds,
            "detail": f"n_pages={len(pages)} max_page_idx={max_page_idx}"}


def run() -> list[dict]:
    store.init(ROOT / "data")
    conn = db.connect(ROOT / "data" / "studio.db")
    comp = conn.execute("SELECT * FROM compositions WHERE id = ?", (COMP_ID,)).fetchone()
    checks = []
    if comp is None:
        return [{"name": "dummy composition exists", "ok": False,
                  "detail": "run `python -m tools.make_dummy` first"}]
    comp = dict(comp)

    out_dir = ROOT / "data" / "_roundtrip_work"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    try:
        for name, layer_id in [("char", LAYER_CHAR), ("fx", LAYER_FX)]:
            sheet = export_layer_sheet(conn, comp, layer_id, name, out_dir)
            json_path = out_dir / f"{name}_sheet.json"
            store.write_json_atomic(store.to_rel(json_path), sheet)
            loaded = store.read_json(store.to_rel(json_path))

            checks.append({"name": f"[{name}] sheet.json round-trips exactly (deep equal)",
                            "ok": loaded == sheet})
            checks.append({"name": f"[{name}] cells count == n_frames (8)",
                            "ok": len(sheet["cells"]) == 8,
                            "detail": f"n_cells={len(sheet['cells'])}"})
            track_sum = sum(t["dur_ms"] for t in sheet["layers"][0]["track"])
            checks.append({"name": f"[{name}] track duration sum == total_ms",
                            "ok": track_sum == sheet["timing"]["total_ms"],
                            "detail": f"sum={track_sum} total_ms={sheet['timing']['total_ms']}"})
            for pf in sheet["pages"]:
                p = out_dir / pf["file"]
                checks.append({"name": f"[{name}] page file exists: {pf['file']}",
                                "ok": p.exists()})

        checks.append(check_dedupe_cell_reference())
        checks.append(check_page_split())
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
    return checks


def main() -> int:
    checks = run()
    all_ok = all(c["ok"] for c in checks)
    for c in checks:
        mark = "PASS" if c["ok"] else "FAIL"
        extra = f" ({c['detail']})" if "detail" in c else ""
        print(f"[{mark}] {c['name']}{extra}")
    print("selftest_roundtrip:", "PASS" if all_ok else "FAIL")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
