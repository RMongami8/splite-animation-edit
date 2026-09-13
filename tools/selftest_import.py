"""自己検証: 外部素材取り込み（プラン §4 core/importers.py 準拠、M1）。

動画・連番(自然順ソート)・静止画・グリッドシート(列数自動推定)・
アニメーションGIF(元durationの復元)のそれぞれについて、実際にffmpeg/Pillowで
フィクスチャを生成し、importers.py の各関数を通して正しくAsset/Frameが
作られることを検証する。DBへの書き込みはテスト後に削除して片付ける。

使い方: python -m tools.selftest_import
"""
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from core import db, importers, store
from core.imageio_ import load_rgba

ROOT = Path(__file__).resolve().parent.parent


def _mk_fixtures(src: Path) -> None:
    import imageio_ffmpeg
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run(
        [exe, "-hide_banner", "-y", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=8",
         "-t", "1", "-pix_fmt", "yuv420p", str(src / "vid.mp4")],
        check=True, capture_output=True, timeout=60,
    )

    for i in [1, 2, 10]:  # 自然順ソートが文字列ソートと食い違う番号を選ぶ
        a = np.zeros((16, 16, 4), np.uint8)
        a[..., 0] = i * 10
        a[..., 3] = 255
        Image.fromarray(a, "RGBA").save(src / f"seq_{i}.png")

    a = np.zeros((20, 24, 4), np.uint8)
    a[..., 1] = 200
    a[..., 3] = 255
    Image.fromarray(a, "RGBA").save(src / "single.png")

    sheet = np.zeros((38, 38, 4), np.uint8)
    sheet[..., 3] = 255
    colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
    for i, (r, c) in enumerate([(0, 0), (0, 1), (1, 0), (1, 1)]):
        x, y = 2 + c * 18, 2 + r * 18
        sheet[y:y + 16, x:x + 16, 0] = colors[i][0]
        sheet[y:y + 16, x:x + 16, 1] = colors[i][1]
        sheet[y:y + 16, x:x + 16, 2] = colors[i][2]
    Image.fromarray(sheet, "RGBA").save(src / "sheet.png")

    frames = []
    for i in range(3):
        a = np.zeros((10, 10, 3), np.uint8)
        a[..., i % 3] = 200
        frames.append(Image.fromarray(a, "RGB"))
    frames[0].save(src / "anim.gif", save_all=True, append_images=frames[1:],
                    duration=[100, 200, 300], loop=0)


def run() -> list[dict]:
    store.init(ROOT / "data")
    conn = db.connect(ROOT / "data" / "studio.db")
    checks = []
    created_asset_ids = []

    src = ROOT / "data" / "_selftest_import_src"
    if src.exists():
        shutil.rmtree(src)
    src.mkdir(parents=True)

    try:
        _mk_fixtures(src)

        pv = importers.probe_decodable(src / "vid.mp4")
        checks.append({"name": "probe_decodable classifies video correctly",
                        "ok": pv is not None and pv["kind"] == "video" and pv["n_frames"] == 8})
        pi = importers.probe_decodable(src / "single.png")
        checks.append({"name": "probe_decodable classifies still image correctly "
                                "(not misclassified as 1-frame video)",
                        "ok": pi is not None and pi["kind"] == "image"})
        pn = importers.probe_decodable(ROOT / "requirements.txt")
        checks.append({"name": "probe_decodable returns None for undecodable file",
                        "ok": pn is None})

        vid_asset = importers.import_video(src / "vid.mp4")
        created_asset_ids.append(vid_asset)
        row = dict(conn.execute("SELECT * FROM assets WHERE id=?", (vid_asset,)).fetchone())
        frames = conn.execute(
            "SELECT * FROM frames WHERE asset_id=? ORDER BY idx", (vid_asset,)
        ).fetchall()
        checks.append({"name": "import_video creates 8 frames with original file preserved",
                        "ok": row["n_frames"] == 8 and len(frames) == 8
                        and store.to_abs(row["rel_path"]).exists()})

        seq_asset = importers.import_sequence(
            [src / "seq_10.png", src / "seq_1.png", src / "seq_2.png"], fps=5)
        created_asset_ids.append(seq_asset)
        seq_frames = conn.execute(
            "SELECT * FROM frames WHERE asset_id=? ORDER BY idx", (seq_asset,)
        ).fetchall()
        r_vals = [load_rgba(store.to_abs(f["rel_path"]))[0, 0, 0] for f in seq_frames]
        checks.append({
            "name": "import_sequence natural-sorts by number, not string "
                    "(seq_1,seq_2,seq_10, not seq_1,seq_10,seq_2)",
            "ok": r_vals == [10, 20, 100], "detail": f"r_vals={r_vals}",
        })

        img_asset = importers.import_image(src / "single.png")
        created_asset_ids.append(img_asset)
        img_row = dict(conn.execute("SELECT * FROM assets WHERE id=?", (img_asset,)).fetchone())
        checks.append({"name": "import_image preserves exact original dimensions (24x20)",
                        "ok": img_row["width"] == 24 and img_row["height"] == 20})

        sheet_asset = importers.import_sheet(
            src / "sheet.png", cell_w=16, cell_h=16, margin=2, spacing=2, count=4)
        created_asset_ids.append(sheet_asset)
        import json
        sheet_row = dict(conn.execute("SELECT * FROM assets WHERE id=?", (sheet_asset,)).fetchone())
        meta = json.loads(sheet_row["meta_json"])
        sheet_frames = conn.execute(
            "SELECT * FROM frames WHERE asset_id=? ORDER BY idx", (sheet_asset,)
        ).fetchall()
        c0 = load_rgba(store.to_abs(sheet_frames[0]["rel_path"]))
        c3 = load_rgba(store.to_abs(sheet_frames[3]["rel_path"]))
        checks.append({
            "name": "import_sheet auto-infers cols from sheet width and extracts correct cells",
            "ok": meta["cols"] == 2 and tuple(c0[8, 8, :3]) == (255, 0, 0)
            and tuple(c3[8, 8, :3]) == (255, 255, 0),
            "detail": f"cols={meta['cols']} c0={list(c0[8,8])} c3={list(c3[8,8])}",
        })

        gif_asset = importers.import_gif_or_webp(src / "anim.gif")
        created_asset_ids.append(gif_asset)
        gif_frames = conn.execute(
            "SELECT * FROM frames WHERE asset_id=? ORDER BY idx", (gif_asset,)
        ).fetchall()
        gif_pts = [f["pts"] for f in gif_frames]
        checks.append({
            "name": "import_gif_or_webp recovers original per-frame durations as PTS",
            "ok": gif_pts == [0, 100, 300], "detail": f"pts={gif_pts}",
        })
    finally:
        # DBとファイルの後片付け(このテスト専用のAssetだけを消す)
        for aid in created_asset_ids:
            frame_dirs = set()
            for r in conn.execute("SELECT rel_path FROM frames WHERE asset_id=?", (aid,)).fetchall():
                p = store.to_abs(r["rel_path"])
                if p.exists():
                    p.unlink()
                frame_dirs.add(p.parent)
            for d in frame_dirs:
                try:
                    d.rmdir()
                except OSError:
                    pass
            row = conn.execute("SELECT rel_path FROM assets WHERE id=?", (aid,)).fetchone()
            if row:
                p = store.to_abs(row["rel_path"])
                if p.exists() and p.is_file():
                    p.unlink()
                    try:
                        p.parent.rmdir()
                    except OSError:
                        pass
        if created_asset_ids:
            placeholders = ",".join("?" for _ in created_asset_ids)
            conn.execute(f"DELETE FROM frames WHERE asset_id IN ({placeholders})", created_asset_ids)
            conn.execute(f"DELETE FROM assets WHERE id IN ({placeholders})", created_asset_ids)
            conn.commit()
        shutil.rmtree(src, ignore_errors=True)

    return checks


def main() -> int:
    checks = run()
    all_ok = all(c["ok"] for c in checks)
    for c in checks:
        mark = "PASS" if c["ok"] else "FAIL"
        extra = f" ({c['detail']})" if "detail" in c else ""
        print(f"[{mark}] {c['name']}{extra}")
    print("selftest_import:", "PASS" if all_ok else "FAIL")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
