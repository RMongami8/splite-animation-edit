"""素材(Asset)関連のHTTP API（プラン §4 準拠）。

POST /api/assets/import は複数ファイルやJSONメタデータを同時に受け取る必要があるため、
純粋なJSONではなく multipart(type/params_jsonをフォームフィールドとして持つ)で実装する
(§4表の「すべてJSON(アップロードのみmultipart)」からの実務上必要な逸脱。
docs/decisions.md に記録する)。
"""
import json
import shutil
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from core import db, importers, store

router = APIRouter()


def _err(status: int, code: str, message: str):
    raise HTTPException(status_code=status, detail={"code": code, "message": message})


def _save_upload_to_tmp(upload: UploadFile) -> Path:
    tmp = store.stage(f"upload_{upload.filename or 'file'}")
    with open(tmp, "wb") as out:
        shutil.copyfileobj(upload.file, out)
    return tmp


@router.get("/api/assets")
def list_assets(kind: str | None = None):
    conn = db.get_conn()
    if kind:
        rows = conn.execute(
            "SELECT * FROM assets WHERE kind = ? ORDER BY created_at DESC", (kind,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM assets ORDER BY created_at DESC").fetchall()
    return {"assets": [_asset_summary(dict(r)) for r in rows]}


def _asset_summary(row: dict) -> dict:
    return {
        "id": row["id"], "kind": row["kind"], "width": row["width"],
        "height": row["height"], "n_frames": row["n_frames"],
        "tb_num": row["tb_num"], "tb_den": row["tb_den"],
        "source": row["source"], "has_alpha": bool(row["has_alpha"]),
        "created_at": row["created_at"],
    }


@router.get("/api/assets/{asset_id}/frames")
def get_asset_frames(asset_id: str):
    conn = db.get_conn()
    asset = conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
    if asset is None:
        _err(404, "not_found", "asset not found")
    rows = conn.execute(
        "SELECT * FROM frames WHERE asset_id = ? ORDER BY idx", (asset_id,)
    ).fetchall()
    frames = []
    for r in rows:
        r = dict(r)
        frames.append({
            "frame_id": r["frame_id"], "idx": r["idx"], "pts": r["pts"],
            "width": r["width"], "height": r["height"],
            "has_alpha": bool(r["has_alpha"]),
            # M1 時点ではサムネイル未生成(§10 性能最適化は後回し)。原寸画像URLを暫定で使う
            "thumb_url": f"/api/files/{r['rel_path']}",
            "image_url": f"/api/files/{r['rel_path']}",
        })
    return {"asset_id": asset_id, "frames": frames}


@router.get("/api/assets/{asset_id}/frame_scores")
def get_frame_scores(asset_id: str):
    """キーフレーム抽出用: 直前フレームとの差分スコア(0-1)。画像そのものは返さない。"""
    from core import keyframes
    conn = db.get_conn()
    if conn.execute("SELECT 1 FROM assets WHERE id = ?", (asset_id,)).fetchone() is None:
        _err(404, "not_found", "asset not found")
    rows = conn.execute(
        "SELECT rel_path FROM frames WHERE asset_id = ? ORDER BY idx", (asset_id,)
    ).fetchall()
    scores = keyframes.frame_diff_scores([store.to_abs(r["rel_path"]) for r in rows])
    return {"asset_id": asset_id, "scores": scores}


@router.post("/api/assets/upload")
async def upload_asset(file: UploadFile = File(...)):
    """単一ファイルをアップロードし、kind を自動判定(probe_decodable)して
    video または image として取り込む。連番/シート/GIF等は /api/assets/import を使う。
    """
    tmp = _save_upload_to_tmp(file)
    try:
        info = importers.probe_decodable(tmp)
        if info is None:
            _err(400, "undecodable", "file could not be decoded as image or video")
        if info["kind"] == "video":
            asset_id = importers.import_video(tmp)
        else:
            asset_id = importers.import_image(tmp)
        return {"asset_id": asset_id, "kind": info["kind"]}
    finally:
        tmp.unlink(missing_ok=True)


@router.post("/api/assets/import")
async def import_asset(
    type: str = Form(...),
    params_json: str = Form("{}"),
    file: UploadFile | None = File(None),
    json_file: UploadFile | None = File(None),
    files: list[UploadFile] | None = File(None),
):
    """type: sequence | sheet | studio_sheet | gif | package | pdf"""
    try:
        params = json.loads(params_json)
    except json.JSONDecodeError:
        _err(400, "bad_params", "params_json is not valid JSON")

    if type == "sequence":
        if not files:
            _err(400, "missing_files", "sequence import requires files[]")
        fps = params.get("fps")
        if not fps or fps <= 0:
            _err(400, "missing_fps", "sequence import requires positive params.fps")
        tmp_paths = [_save_upload_to_tmp(f) for f in files]
        try:
            asset_id = importers.import_sequence(tmp_paths, fps=fps)
        finally:
            for p in tmp_paths:
                p.unlink(missing_ok=True)
        return {"asset_id": asset_id}

    if type == "sheet":
        if not file:
            _err(400, "missing_file", "sheet import requires file")
        required = ["cell_w", "cell_h", "count"]
        missing = [k for k in required if k not in params]
        if missing:
            _err(400, "missing_params", f"sheet import requires params: {missing}")
        tmp = _save_upload_to_tmp(file)
        try:
            asset_id = importers.import_sheet(
                tmp, cell_w=params["cell_w"], cell_h=params["cell_h"],
                margin=params.get("margin", 0), spacing=params.get("spacing", 0),
                count=params["count"],
            )
        finally:
            tmp.unlink(missing_ok=True)
        return {"asset_id": asset_id}

    if type == "studio_sheet":
        if not file or not json_file:
            _err(400, "missing_file", "studio_sheet import requires file (png) and json_file")
        tmp_png = _save_upload_to_tmp(file)
        tmp_json = _save_upload_to_tmp(json_file)
        try:
            asset_id = importers.import_studio_sheet(tmp_png, tmp_json)
        finally:
            tmp_png.unlink(missing_ok=True)
            tmp_json.unlink(missing_ok=True)
        return {"asset_id": asset_id}

    if type == "gif":
        if not file:
            _err(400, "missing_file", "gif import requires file")
        tmp = _save_upload_to_tmp(file)
        try:
            asset_id = importers.import_gif_or_webp(tmp)
        finally:
            tmp.unlink(missing_ok=True)
        return {"asset_id": asset_id}

    if type in ("package", "pdf"):
        _err(501, "not_implemented", f"{type} import is scheduled for a later milestone")

    _err(400, "bad_type", f"unknown import type: {type!r}")
