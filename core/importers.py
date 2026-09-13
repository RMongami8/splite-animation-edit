"""外部素材と①の生成素材を同じ処理で共通データへ変換する（プラン §4 importers.py 契約準拠）。

規則:
- 不足情報だけを聞く。連番はfpsのみ、シートはセル寸法のみ。cols はシート画像の
  実幅から自動推定する(呼び出し側に列数を聞かない)。
- 寸法混在は「元サイズ保持＋共通キャンバス配置」。ここでは勝手に拡大縮小しない
  （共通キャンバスへの配置は Composition/Exposure の dx/dy が担当し、import 側は
  各フレームの実サイズを frames テーブルにそのまま記録するだけ）。
- 自然順ソート: re.split(r'(\\d+)', name) で数値部をintにして比較(文字列ソートにしない)。
- originals/ は追記のみ: 単一の元ファイルから再現できないもの(アップロードされた
  動画そのもの、連番画像そのもの、シート画像そのもの)をここに置く。derived/ は
  原本から再生成できる派生データ(動画から抽出したフレーム、シートから切り出した
  セル)を置く。
- ファイルは先に store.commit() で確定保存してから、最後にまとめて1トランザクション
  で assets/frames 行を挿入する。クラッシュ時に「DB行はあるがファイルが無い」状態には
  ならない(逆に「ファイルはあるがDB行が無い」孤児は起こり得るが、derived/ 配下なら
  無害な再生成可能ゴミ、originals/ 配下でも DB 行が無ければ起動時の recover_pending
  や将来の整合性チェックで検出できる)。
"""
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

from core import db, store, video
from core.ids import new_id
from core.imageio_ import load_rgba, save_png


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _natural_sort_key(name: str):
    parts = re.split(r"(\d+)", name)
    return [int(p) if p.isdigit() else p for p in parts]


def probe_decodable(path: Path) -> dict | None:
    """拡張子で判定せず、実際にデコードできるかを試す。動画→画像の順に試す。
    デコードできなければ None を返す。

    注意: PyAV は単体の静止画(PNG等)も image2 デマルチプレクサ経由で「1フレームの
    動画」として開けてしまう。n_frames>1 を条件にすることで、静止画が誤って
    kind="video" に分類されるのを防ぐ(実用上、本アプリが扱う動画素材は常に複数
    フレームを持つため、この閾値で十分)。
    """
    path = Path(path)
    try:
        info = video.probe(path)
        if info.get("n_frames", 0) > 1 and info.get("width", 0) > 0:
            return {"kind": "video", **info}
    except Exception:
        pass
    try:
        with Image.open(path) as img:
            n_frames = getattr(img, "n_frames", 1)
            return {"kind": "image", "width": img.width, "height": img.height,
                    "n_frames": n_frames, "format": img.format}
    except Exception:
        pass
    return None


def _insert_asset(conn, asset_id: str, kind: str, rel_path: str, sha256: str,
                   width: int, height: int, n_frames: int, tb_num, tb_den,
                   rotation: int, has_alpha: bool, source: str, meta: dict) -> None:
    conn.execute(
        "INSERT INTO assets(id, kind, rel_path, sha256, width, height, n_frames, "
        "tb_num, tb_den, rotation, has_alpha, source, attempt_id, meta_json, "
        "created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (asset_id, kind, rel_path, sha256, width, height, n_frames, tb_num, tb_den,
         rotation, int(has_alpha), source, None, json.dumps(meta, ensure_ascii=False),
         _now_iso()),
    )


def _insert_frame(conn, asset_id: str, frame_id: str, idx: int, pts,
                   rel_path: str, width: int, height: int, has_alpha: bool) -> None:
    conn.execute(
        "INSERT INTO frames(asset_id, frame_id, idx, pts, rel_path, width, height, "
        "has_alpha) VALUES (?,?,?,?,?,?,?,?)",
        (asset_id, frame_id, idx, pts, rel_path, width, height, int(has_alpha)),
    )


def import_video(path: Path) -> str:
    """動画を取り込む。元動画は originals/ に保存し、フレームは derived/frames/ に抽出する。
    時刻は video.probe() の実測PTS(有理数timebase)をそのまま frames.pts に記録する。
    """
    path = Path(path)
    info = video.probe(path)
    if info["n_frames"] == 0:
        raise ValueError(f"no frames decoded from video: {path}")

    asset_id = new_id("asset")
    ext = path.suffix or ".mp4"

    tmp_src = store.stage(f"{asset_id}_src{ext}")
    shutil.copyfile(path, tmp_src)
    src_sha = store.sha256_of(tmp_src)
    src_rel = store.commit(tmp_src, f"originals/{asset_id}/src{ext}")

    tmp_frame_dir = store.root() / "tmp" / f"{asset_id}_frames"
    tmp_frame_dir.mkdir(parents=True, exist_ok=True)
    try:
        extracted = video.extract_frames(path, tmp_frame_dir)
        frame_rows = []
        for f in extracted:
            dest_rel = f"derived/frames/{asset_id}/{f['frame_id']}.png"
            committed_rel = store.commit(Path(f["rel_path"]), dest_rel)
            frame_rows.append((f, committed_rel))
    finally:
        shutil.rmtree(tmp_frame_dir, ignore_errors=True)

    conn = db.get_conn()
    with db.write_lock():
        _insert_asset(conn, asset_id, "video", src_rel, src_sha,
                       info["width"], info["height"], info["n_frames"],
                       info["tb_num"], info["tb_den"], info["rotation"],
                       False, "upload",
                       {"codec": info["codec"],
                        "last_frame_dur_pts": info["last_frame_dur_pts"],
                        "start_pts": info["start_pts"]})
        for f, rel in frame_rows:
            _insert_frame(conn, asset_id, f["frame_id"], f["idx"], f["pts"], rel,
                          f["width"], f["height"], False)
        conn.commit()
    return asset_id


def import_sequence(paths: list[Path], fps: int) -> str:
    """連番画像を1本のAssetとして取り込む。自然順ソートし、fps から一定間隔のPTSを割り当てる
    (tb_num=1, tb_den=fps とし、i番目フレームのpts=i とする＝ i/fps 秒)。
    各フレームの実サイズはそのまま記録する(寸法混在があっても拡大縮小しない)。
    """
    if not paths:
        raise ValueError("import_sequence requires at least one path")
    if fps <= 0:
        raise ValueError(f"fps must be positive, got {fps}")

    sorted_paths = sorted((Path(p) for p in paths),
                           key=lambda p: _natural_sort_key(p.name))

    asset_id = new_id("asset")
    frame_rows = []
    max_w, max_h = 0, 0
    any_alpha = False
    for i, p in enumerate(sorted_paths):
        frame_id = f"f{i:04d}"
        with Image.open(p) as img:
            has_alpha = img.mode in ("RGBA", "LA") or "transparency" in img.info
            rgba = np.array(img.convert("RGBA"), dtype=np.uint8)
        ext = p.suffix or ".png"
        dest_rel = f"originals/{asset_id}/{frame_id}{ext}"
        tmp = store.stage(f"{asset_id}_{frame_id}{ext}")
        save_png(tmp, rgba) if ext.lower() == ".png" else shutil.copyfile(p, tmp)
        committed_rel = store.commit(tmp, dest_rel)
        w, h = rgba.shape[1], rgba.shape[0]
        max_w, max_h = max(max_w, w), max(max_h, h)
        any_alpha = any_alpha or has_alpha
        frame_rows.append({
            "frame_id": frame_id, "idx": i, "pts": i,
            "rel_path": committed_rel, "width": w, "height": h,
            "has_alpha": has_alpha,
        })

    conn = db.get_conn()
    with db.write_lock():
        _insert_asset(conn, asset_id, "sequence",
                       frame_rows[0]["rel_path"], "n/a", max_w, max_h,
                       len(frame_rows), 1, fps, 0, any_alpha, "upload",
                       {"note": "元サイズ混在の可能性あり。frames テーブルの width/height を見ること"})
        for f in frame_rows:
            _insert_frame(conn, asset_id, f["frame_id"], f["idx"], f["pts"],
                          f["rel_path"], f["width"], f["height"], f["has_alpha"])
        conn.commit()
    return asset_id


def import_image(path: Path) -> str:
    """1枚の画像を、1フレームのAssetとして取り込む(静止レイヤーやFirst Frame用)。"""
    path = Path(path)
    with Image.open(path) as img:
        has_alpha = img.mode in ("RGBA", "LA") or "transparency" in img.info
        rgba = np.array(img.convert("RGBA"), dtype=np.uint8)
    w, h = rgba.shape[1], rgba.shape[0]

    asset_id = new_id("asset")
    ext = path.suffix or ".png"
    tmp = store.stage(f"{asset_id}_src{ext}")
    if ext.lower() == ".png":
        save_png(tmp, rgba)
    else:
        shutil.copyfile(path, tmp)
    src_sha = store.sha256_of(tmp)
    src_rel = store.commit(tmp, f"originals/{asset_id}/src{ext}")

    conn = db.get_conn()
    with db.write_lock():
        _insert_asset(conn, asset_id, "image", src_rel, src_sha, w, h, 1,
                       None, None, 0, has_alpha, "upload", {})
        _insert_frame(conn, asset_id, "f0000", 0, 0, src_rel, w, h, has_alpha)
        conn.commit()
    return asset_id


def import_sheet(path: Path, cell_w: int, cell_h: int, margin: int,
                  spacing: int, count: int) -> str:
    """グリッドシート画像をセルに分割して取り込む。列数はシート画像の実幅から自動推定する
    (margin を画像端の余白、spacing をセル間の余白として、収まる最大列数を使う)。
    行優先(左上から右へ、末尾まで来たら次の行)で count 個のセルを切り出す。
    元シート画像は originals/、切り出したセルは derived/frames/ に保存する
    (セルはシートから再生成できる派生データのため)。
    """
    path = Path(path)
    sheet_rgba = load_rgba(path)
    sheet_h, sheet_w = sheet_rgba.shape[:2]

    usable_w = sheet_w - 2 * margin
    stride_w = cell_w + spacing
    cols = max(1, (usable_w + spacing) // stride_w)
    stride_h = cell_h + spacing

    asset_id = new_id("asset")

    tmp_src = store.stage(f"{asset_id}_sheet.png")
    save_png(tmp_src, sheet_rgba)
    src_sha = store.sha256_of(tmp_src)
    src_rel = store.commit(tmp_src, f"originals/{asset_id}/src.png")

    frame_rows = []
    for i in range(count):
        r, c = divmod(i, cols)
        x = margin + c * stride_w
        y = margin + r * stride_h
        if x + cell_w > sheet_w or y + cell_h > sheet_h:
            raise ValueError(
                f"cell index {i} (row={r}, col={c}) exceeds sheet bounds "
                f"({sheet_w}x{sheet_h}) with cell_wh=({cell_w},{cell_h}) "
                f"margin={margin} spacing={spacing} cols={cols}"
            )
        cell = sheet_rgba[y:y + cell_h, x:x + cell_w].copy()
        frame_id = f"f{i:04d}"
        tmp_cell = store.stage(f"{asset_id}_{frame_id}.png")
        save_png(tmp_cell, cell)
        dest_rel = f"derived/frames/{asset_id}/{frame_id}.png"
        committed_rel = store.commit(tmp_cell, dest_rel)
        frame_rows.append({
            "frame_id": frame_id, "idx": i, "pts": i, "rel_path": committed_rel,
            "width": cell_w, "height": cell_h,
        })

    conn = db.get_conn()
    with db.write_lock():
        _insert_asset(conn, asset_id, "sheet", src_rel, src_sha, cell_w, cell_h,
                       count, 1, 1, 0, True, "upload",
                       {"cols": int(cols), "margin": margin, "spacing": spacing,
                        "sheet_w": sheet_w, "sheet_h": sheet_h})
        for f in frame_rows:
            _insert_frame(conn, asset_id, f["frame_id"], f["idx"], f["pts"],
                          f["rel_path"], f["width"], f["height"], True)
        conn.commit()
    return asset_id


def import_studio_sheet(png: Path, sheet_json: Path) -> str:
    """本アプリが出した sheet.json + シートPNG からコマ順・時間・pivotを復元する。

    M1 時点では単一ページの sheet.json のみ対応する(複数ページはエラーにする)。
    各セルを1フレームのAssetとして取り込み、sheet.json全体(timing/pivot/layers[].track)
    は assets.meta_json["studio_sheet"] にそのまま保存する。呼び出し側(HTTP API)は
    これを読み、Composition/Layer/Exposure を組み立てる(コマ順=track、時間=dur_ms、
    pivot=pivot)。
    """
    sheet = json.loads(Path(sheet_json).read_text(encoding="utf-8"))
    if sheet.get("format") != "spritesheet-studio/sheet@1":
        raise ValueError(f"unknown sheet.json format: {sheet.get('format')!r}")
    if len(sheet["pages"]) != 1:
        raise ValueError(
            f"import_studio_sheet supports single-page sheets only in M1 "
            f"(got {len(sheet['pages'])} pages); multi-page import is a later milestone"
        )

    page_rgba = load_rgba(png)
    asset_id = new_id("asset")

    tmp_src = store.stage(f"{asset_id}_sheet.png")
    save_png(tmp_src, page_rgba)
    src_sha = store.sha256_of(tmp_src)
    src_rel = store.commit(tmp_src, f"originals/{asset_id}/src.png")

    frame_rows = []
    for i, cell in enumerate(sheet["cells"]):
        x, y, w, h = cell["x"], cell["y"], cell["w"], cell["h"]
        cropped = page_rgba[y:y + h, x:x + w].copy()
        frame_id = f"f{i:04d}"
        tmp_cell = store.stage(f"{asset_id}_{frame_id}.png")
        save_png(tmp_cell, cropped)
        dest_rel = f"derived/frames/{asset_id}/{frame_id}.png"
        committed_rel = store.commit(tmp_cell, dest_rel)
        frame_rows.append({
            "frame_id": frame_id, "idx": i, "pts": i, "rel_path": committed_rel,
            "width": w, "height": h, "cell_id": cell["id"],
        })

    cell_id_to_frame_id = {f["cell_id"]: f["frame_id"] for f in frame_rows}

    conn = db.get_conn()
    with db.write_lock():
        _insert_asset(conn, asset_id, "sheet", src_rel, src_sha,
                       sheet["canvas"]["w"], sheet["canvas"]["h"], len(frame_rows),
                       sheet["timing"]["tick_rate"], sheet["timing"]["tick_rate"],
                       0, True, "imported",
                       {"studio_sheet": sheet, "cell_id_to_frame_id": cell_id_to_frame_id})
        for f in frame_rows:
            _insert_frame(conn, asset_id, f["frame_id"], f["idx"], f["pts"],
                          f["rel_path"], f["width"], f["height"], True)
        conn.commit()
    return asset_id


def import_gif_or_webp(path: Path) -> str:
    """アニメーションGIF/WebPを取り込む。元のフレーム表示時間(duration)をそのまま
    pts(ミリ秒, tb_num=1 tb_den=1000)として復元する。合成状態(disposal)は Pillow の
    .convert("RGBA") が各フレームを合成した結果を使う(disposalを厳密に再現するのは
    重い処理のため、M1では「見た目通りの合成結果」を1フレームとして扱う簡易実装)。
    """
    path = Path(path)
    asset_id = new_id("asset")

    tmp_src = store.stage(f"{asset_id}_src{path.suffix}")
    shutil.copyfile(path, tmp_src)
    src_sha = store.sha256_of(tmp_src)
    src_rel = store.commit(tmp_src, f"originals/{asset_id}/src{path.suffix}")

    frame_rows = []
    with Image.open(path) as img:
        n_frames = getattr(img, "n_frames", 1)
        pts_ms = 0
        max_w, max_h = 0, 0
        for i in range(n_frames):
            img.seek(i)
            duration = img.info.get("duration", 100)  # ms, Pillow既定は100ms
            rgba = np.array(img.convert("RGBA"), dtype=np.uint8)
            frame_id = f"f{i:04d}"
            dest_rel = f"derived/frames/{asset_id}/{frame_id}.png"
            tmp_frame = store.stage(f"{asset_id}_{frame_id}.png")
            save_png(tmp_frame, rgba)
            committed_rel = store.commit(tmp_frame, dest_rel)
            w, h = rgba.shape[1], rgba.shape[0]
            max_w, max_h = max(max_w, w), max(max_h, h)
            frame_rows.append({
                "frame_id": frame_id, "idx": i, "pts": pts_ms,
                "rel_path": committed_rel, "width": w, "height": h,
            })
            pts_ms += duration

    conn = db.get_conn()
    with db.write_lock():
        _insert_asset(conn, asset_id, "sequence", src_rel, src_sha, max_w, max_h,
                       len(frame_rows), 1, 1000, 0, True, "upload",
                       {"source_format": "gif_or_webp"})
        for f in frame_rows:
            _insert_frame(conn, asset_id, f["frame_id"], f["idx"], f["pts"],
                          f["rel_path"], f["width"], f["height"], True)
        conn.commit()
    return asset_id


def import_package(zip_path: Path) -> dict:
    """§8 ZIP+manifest 往復。core/pkgio.py 実装後(M2)に対応する。"""
    raise NotImplementedError(
        "import_package requires core/pkgio.py, which is scheduled for M2"
    )


def import_pdf(path: Path) -> dict:
    """PDF取り込み。core/pdfio.py 実装後(M5)に対応する。"""
    raise NotImplementedError(
        "import_pdf requires core/pdfio.py, which is scheduled for M5"
    )
