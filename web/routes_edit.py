"""Composition/Layer/Exposure の編集API（プラン §4 準拠）。

規則:
- 並べ替え・一括更新は PUT /api/layers/{id}/exposures の1リクエストに集約する
  (全行置換・1トランザクション。exposures.ord に UNIQUE を付けない理由はこれ)。
- 変更のたびに compositions.revision を進める。total_ticks はレイヤー構成が
  変わる操作(レイヤー追加/削除、exposures一括置換、hold_ticks変更)の後で
  再計算する(最後のコマの終了時刻を含む = 最後のholdが尺に含まれる)。
- 応答不明な生成POSTの再送はしない、という規則は生成API(M3)向け。ここは
  同期的なローカル編集のみを扱う。
"""
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from typing import Literal

from pydantic import BaseModel, Field

from core import db, store
from core.ids import new_id
from core.imageio_ import load_rgba, save_png
from core.timeline import exposure_spans

router = APIRouter()


def _err(status: int, code: str, message: str):
    raise HTTPException(status_code=status, detail={"code": code, "message": message})


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_comp_or_404(conn, comp_id: str) -> dict:
    row = conn.execute("SELECT * FROM compositions WHERE id = ?", (comp_id,)).fetchone()
    if row is None:
        _err(404, "not_found", "composition not found")
    return dict(row)


def _get_layer_or_404(conn, layer_id: str) -> dict:
    row = conn.execute("SELECT * FROM layers WHERE id = ?", (layer_id,)).fetchone()
    if row is None:
        _err(404, "not_found", "layer not found")
    return dict(row)


def _recompute_total_ticks(conn, comp_id: str) -> int:
    """全レイヤーの (start_ticks + hold合計) の最大値をComposition全体尺にする。
    最後のコマの終了時刻を含む(= 最後のholdが尺に含まれる)ことを保証する。
    """
    layers = conn.execute(
        "SELECT id, start_ticks FROM layers WHERE comp_id = ?", (comp_id,)
    ).fetchall()
    max_end = 0
    for ly in layers:
        holds = [r["hold_ticks"] for r in conn.execute(
            "SELECT hold_ticks FROM exposures WHERE layer_id = ? ORDER BY ord",
            (ly["id"],),
        ).fetchall()]
        layer_end = ly["start_ticks"] + sum(holds)
        max_end = max(max_end, layer_end)
    conn.execute(
        "UPDATE compositions SET total_ticks = ?, revision = revision + 1, "
        "updated_at = ? WHERE id = ?",
        (max_end, _now_iso(), comp_id),
    )
    return max_end


def _touch_composition(conn, comp_id: str) -> None:
    conn.execute(
        "UPDATE compositions SET revision = revision + 1, updated_at = ? WHERE id = ?",
        (_now_iso(), comp_id),
    )


def _layer_out(conn, ly: dict) -> dict:
    exp_rows = conn.execute(
        "SELECT * FROM exposures WHERE layer_id = ? ORDER BY ord", (ly["id"],)
    ).fetchall()
    exposures = []
    for e in exp_rows:
        e = dict(e)
        frame = conn.execute(
            "SELECT rel_path FROM frames WHERE asset_id = ? AND frame_id = ?",
            (e["asset_id"], e["frame_id"]),
        ).fetchone()
        exposures.append({
            "id": e["id"], "ord": e["ord"], "asset_id": e["asset_id"],
            "frame_id": e["frame_id"], "hold_ticks": e["hold_ticks"],
            "dx": e["dx"], "dy": e["dy"], "flip_x": bool(e["flip_x"]),
            "scale": e["scale"],
            "matte_mode": e["matte_mode"],
            "matte_json": json.loads(e["matte_json"]),
            "image_url": f"/api/files/{frame['rel_path']}" if frame else None,
        })
    return {
        "id": ly["id"], "comp_id": ly["comp_id"], "name": ly["name"],
        "kind": ly["kind"], "blend": ly["blend"], "opacity": ly["opacity"],
        "z": ly["z"], "start_ticks": ly["start_ticks"], "after_end": ly["after_end"],
        "visible": bool(ly["visible"]),
        "matte_json": json.loads(ly["matte_json"]),
        "anchor_json": json.loads(ly["anchor_json"]),
        "exposures": exposures,
    }


def _comp_out(conn, comp: dict) -> dict:
    layer_rows = conn.execute(
        "SELECT * FROM layers WHERE comp_id = ? ORDER BY z", (comp["id"],)
    ).fetchall()
    return {
        "id": comp["id"], "name": comp["name"],
        "canvas_w": comp["canvas_w"], "canvas_h": comp["canvas_h"],
        "tick_rate": comp["tick_rate"], "total_ticks": comp["total_ticks"],
        "loop": bool(comp["loop"]), "revision": comp["revision"],
        "layers": [_layer_out(conn, dict(r)) for r in layer_rows],
    }


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------

class CreateCompBody(BaseModel):
    name: str
    canvas_w: int
    canvas_h: int
    loop: bool = True


@router.post("/api/comps")
def create_composition(body: CreateCompBody):
    conn = db.get_conn()
    comp_id = new_id("composition")
    now = _now_iso()
    with db.write_lock():
        conn.execute(
            "INSERT INTO compositions(id, name, canvas_w, canvas_h, tick_rate, "
            "total_ticks, loop, revision, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (comp_id, body.name, body.canvas_w, body.canvas_h, 1000, 0,
             int(body.loop), 1, now, now),
        )
        conn.commit()
    return _comp_out(conn, _get_comp_or_404(conn, comp_id))


@router.get("/api/comps/{comp_id}")
def get_composition(comp_id: str):
    conn = db.get_conn()
    comp = _get_comp_or_404(conn, comp_id)
    return _comp_out(conn, comp)


class PatchCompBody(BaseModel):
    name: str | None = None
    canvas_w: int | None = None
    canvas_h: int | None = None
    loop: bool | None = None


@router.patch("/api/comps/{comp_id}")
def patch_composition(comp_id: str, body: PatchCompBody):
    conn = db.get_conn()
    _get_comp_or_404(conn, comp_id)
    fields = {}
    if body.name is not None:
        fields["name"] = body.name
    if body.canvas_w is not None:
        fields["canvas_w"] = body.canvas_w
    if body.canvas_h is not None:
        fields["canvas_h"] = body.canvas_h
    if body.loop is not None:
        fields["loop"] = int(body.loop)
    if not fields:
        return _comp_out(conn, _get_comp_or_404(conn, comp_id))
    fields["revision_bump"] = 1
    cols = ", ".join(f"{k} = ?" for k in fields if k != "revision_bump")
    values = [v for k, v in fields.items() if k != "revision_bump"]
    with db.write_lock():
        conn.execute(
            f"UPDATE compositions SET {cols}, revision = revision + 1, "
            f"updated_at = ? WHERE id = ?",
            values + [_now_iso(), comp_id],
        )
        conn.commit()
    return _comp_out(conn, _get_comp_or_404(conn, comp_id))


# ---------------------------------------------------------------------------
# Layer
# ---------------------------------------------------------------------------

class CreateLayerBody(BaseModel):
    name: str
    kind: str = "normal"          # normal|glow|smoke
    blend: str = "normal"         # normal|add
    z: int = 0
    opacity: float = 1.0
    start_ticks: int = 0
    after_end: str = "hold"       # loop|hold|hide
    asset_id: str
    frame_start_idx: int = 0
    frame_end_idx: int | None = None   # None = 末尾まで(含む)
    last_hold_ticks: int | None = None  # 動画/連番の最終コマの表示時間(未指定なら直前間隔を流用)
    static_hold_ticks: int = 1000       # kind=image の素材を使うときの単一露出の表示時間
    # --- 抽出オプション(docs/decisions.md「タイムライン編集拡張」) ---
    frame_indices: list[int] | None = None   # 範囲内で採用するフレーム idx(None=全部)
    hold_mode: Literal["source", "fixed"] = "source"  # source=元の尺を保つ / fixed=一定
    fixed_hold_ticks: int = Field(100, ge=1)


def _holds_from_asset_frames(conn, asset: dict, frame_start_idx: int,
                              frame_end_idx: int | None, tick_rate: int,
                              last_hold_ticks: int | None,
                              static_hold_ticks: int,
                              frame_indices: list[int] | None = None,
                              hold_mode: str = "source",
                              fixed_hold_ticks: int = 100) -> list[tuple[str, int]]:
    """asset の frames から (frame_id, hold_ticks) のリストを作る。

    tb_num/tb_den が無い(静止画1枚)場合は static_hold_ticks を単一露出として使う。
    有る場合は連続フレーム間の実測PTS差をticksに変換してholdにし、最終フレームは
    last_hold_ticks(未指定なら直前フレームとの間隔を流用)を使う。

    frame_indices で間引く場合、hold_mode="source" では各コマを「次に採用したコマの
    開始」まで、最後のコマを「範囲の終端」まで伸ばすので、範囲全体の尺は保たれる。
    hold_mode="fixed" では全コマ fixed_hold_ticks。
    """
    from core.timeline import pts_to_ticks

    frames = conn.execute(
        "SELECT * FROM frames WHERE asset_id = ? ORDER BY idx", (asset["id"],)
    ).fetchall()
    frames = [dict(f) for f in frames]
    if frame_end_idx is None:
        frame_end_idx = frames[-1]["idx"] if frames else 0
    selected = [f for f in frames if frame_start_idx <= f["idx"] <= frame_end_idx]
    if not selected:
        raise ValueError("no frames in the requested range")

    picked = selected
    if frame_indices is not None:
        wanted = set(frame_indices)
        picked = [f for f in selected if f["idx"] in wanted]
        if not picked:
            raise ValueError("frame_indices selects no frames in the range")

    if hold_mode == "fixed":
        return [(f["frame_id"], fixed_hold_ticks) for f in picked]

    if asset["tb_num"] is None or asset["tb_den"] is None or len(selected) == 1:
        # 単一露出扱い(静止画、または範囲がフレーム1枚のみ)
        return [(f["frame_id"], static_hold_ticks) for f in picked]

    tb_num, tb_den = asset["tb_num"], asset["tb_den"]
    ticks = {f["idx"]: pts_to_ticks(f["pts"], tb_num, tb_den, tick_rate) for f in selected}
    if last_hold_ticks is None:
        last_hold_ticks = ticks[selected[-1]["idx"]] - ticks[selected[-2]["idx"]]
    range_end = ticks[selected[-1]["idx"]] + last_hold_ticks
    holds = []
    for i, f in enumerate(picked):
        end = ticks[picked[i + 1]["idx"]] if i + 1 < len(picked) else range_end
        holds.append((f["frame_id"], end - ticks[f["idx"]]))
    return holds


@router.post("/api/comps/{comp_id}/layers")
def create_layer(comp_id: str, body: CreateLayerBody):
    conn = db.get_conn()
    comp = _get_comp_or_404(conn, comp_id)
    asset = conn.execute(
        "SELECT * FROM assets WHERE id = ?", (body.asset_id,)
    ).fetchone()
    if asset is None:
        _err(404, "not_found", "asset not found")
    asset = dict(asset)

    try:
        holds = _holds_from_asset_frames(
            conn, asset, body.frame_start_idx, body.frame_end_idx,
            comp["tick_rate"], body.last_hold_ticks, body.static_hold_ticks,
            body.frame_indices, body.hold_mode, body.fixed_hold_ticks,
        )
    except ValueError as e:
        _err(400, "bad_frame_range", str(e))

    layer_id = new_id("layer")
    with db.write_lock():
        conn.execute(
            "INSERT INTO layers(id, comp_id, name, kind, blend, opacity, z, "
            "start_ticks, after_end, visible, matte_json, anchor_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (layer_id, comp_id, body.name, body.kind, body.blend, body.opacity,
             body.z, body.start_ticks, body.after_end, 1, "{}", "{}"),
        )
        for i, (frame_id, hold) in enumerate(holds):
            conn.execute(
                "INSERT INTO exposures(id, layer_id, ord, asset_id, frame_id, "
                "hold_ticks, dx, dy, flip_x, matte_mode, matte_json, scale) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (new_id("exposure"), layer_id, i, asset["id"], frame_id, hold,
                 0, 0, 0, "inherit", "{}", 1.0),
            )
        _recompute_total_ticks(conn, comp_id)
        conn.commit()
    return _layer_out(conn, _get_layer_or_404(conn, layer_id))


class PatchLayerBody(BaseModel):
    name: str | None = None
    blend: str | None = None
    opacity: float | None = None
    z: int | None = None
    start_ticks: int | None = None
    after_end: str | None = None
    visible: bool | None = None
    matte_json: dict | None = None
    anchor_json: dict | None = None


@router.patch("/api/layers/{layer_id}")
def patch_layer(layer_id: str, body: PatchLayerBody):
    conn = db.get_conn()
    layer = _get_layer_or_404(conn, layer_id)
    fields = {}
    for key in ("name", "blend", "opacity", "z", "start_ticks", "after_end"):
        val = getattr(body, key)
        if val is not None:
            fields[key] = val
    if body.visible is not None:
        fields["visible"] = int(body.visible)
    if body.matte_json is not None:
        fields["matte_json"] = json.dumps(body.matte_json, ensure_ascii=False)
    if body.anchor_json is not None:
        fields["anchor_json"] = json.dumps(body.anchor_json, ensure_ascii=False)

    if fields:
        cols = ", ".join(f"{k} = ?" for k in fields)
        with db.write_lock():
            conn.execute(f"UPDATE layers SET {cols} WHERE id = ?",
                         list(fields.values()) + [layer_id])
            if "start_ticks" in fields:
                _recompute_total_ticks(conn, layer["comp_id"])
            else:
                _touch_composition(conn, layer["comp_id"])
            conn.commit()
    return _layer_out(conn, _get_layer_or_404(conn, layer_id))


@router.delete("/api/layers/{layer_id}")
def delete_layer(layer_id: str):
    conn = db.get_conn()
    layer = _get_layer_or_404(conn, layer_id)
    with db.write_lock():
        conn.execute("DELETE FROM layers WHERE id = ?", (layer_id,))  # exposures は CASCADE
        _recompute_total_ticks(conn, layer["comp_id"])
        conn.commit()
    return {"deleted": layer_id}


# ---------------------------------------------------------------------------
# Exposure
# ---------------------------------------------------------------------------

class ExposureIn(BaseModel):
    id: str | None = None  # 既存IDを指定すると引き継ぐ(無ければ新規発行)
    asset_id: str
    frame_id: str
    hold_ticks: int
    dx: int = 0
    dy: int = 0
    flip_x: bool = False
    scale: float = Field(1.0, ge=0.05, le=8.0)
    matte_mode: str = "inherit"
    matte_json: dict = {}


class PutExposuresBody(BaseModel):
    exposures: list[ExposureIn]


@router.put("/api/layers/{layer_id}/exposures")
def replace_exposures(layer_id: str, body: PutExposuresBody):
    """並べ替え・一括更新はこの1リクエストに集約する(全行置換・1トランザクション)。"""
    conn = db.get_conn()
    layer = _get_layer_or_404(conn, layer_id)
    with db.write_lock():
        conn.execute("DELETE FROM exposures WHERE layer_id = ?", (layer_id,))
        for i, e in enumerate(body.exposures):
            exp_id = e.id or new_id("exposure")
            conn.execute(
                "INSERT INTO exposures(id, layer_id, ord, asset_id, frame_id, "
                "hold_ticks, dx, dy, flip_x, matte_mode, matte_json, scale) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (exp_id, layer_id, i, e.asset_id, e.frame_id, e.hold_ticks,
                 e.dx, e.dy, int(e.flip_x), e.matte_mode,
                 json.dumps(e.matte_json, ensure_ascii=False), e.scale),
            )
        _recompute_total_ticks(conn, layer["comp_id"])
        conn.commit()
    return _layer_out(conn, _get_layer_or_404(conn, layer_id))


class PatchExposureBody(BaseModel):
    hold_ticks: int | None = None
    dx: int | None = None
    dy: int | None = None
    flip_x: bool | None = None
    scale: float | None = Field(None, ge=0.05, le=8.0)
    matte_mode: str | None = None
    matte_json: dict | None = None


@router.patch("/api/exposures/{exposure_id}")
def patch_exposure(exposure_id: str, body: PatchExposureBody):
    conn = db.get_conn()
    exp = conn.execute("SELECT * FROM exposures WHERE id = ?", (exposure_id,)).fetchone()
    if exp is None:
        _err(404, "not_found", "exposure not found")
    exp = dict(exp)
    layer = _get_layer_or_404(conn, exp["layer_id"])

    fields = {}
    for key in ("hold_ticks", "dx", "dy", "scale", "matte_mode"):
        val = getattr(body, key)
        if val is not None:
            fields[key] = val
    if body.flip_x is not None:
        fields["flip_x"] = int(body.flip_x)
    if body.matte_json is not None:
        fields["matte_json"] = json.dumps(body.matte_json, ensure_ascii=False)

    if fields:
        cols = ", ".join(f"{k} = ?" for k in fields)
        with db.write_lock():
            conn.execute(f"UPDATE exposures SET {cols} WHERE id = ?",
                         list(fields.values()) + [exposure_id])
            if "hold_ticks" in fields:
                _recompute_total_ticks(conn, layer["comp_id"])
            else:
                _touch_composition(conn, layer["comp_id"])
            conn.commit()
    return _layer_out(conn, _get_layer_or_404(conn, exp["layer_id"]))


@router.post("/api/exposures/{exposure_id}/replace")
async def replace_exposure_image(exposure_id: str, file: UploadFile = File(...)):
    """1コマだけ画像をドラッグ&ドロップ差し替え。hold_ticks/dx/dy/レイヤー帰属は保持する。
    差し替え画像は新規Asset(kind="image", source="imported")として originals/ に保存し、
    この Exposure の asset_id/frame_id だけを差し替える(他のExposureには影響しない)。
    透過済みPNGの場合は matte_mode を "skip" にする(既存クロマキー設定を自動で
    掛け直さない §5 の規則)。
    """
    conn = db.get_conn()
    exp = conn.execute("SELECT * FROM exposures WHERE id = ?", (exposure_id,)).fetchone()
    if exp is None:
        _err(404, "not_found", "exposure not found")
    exp = dict(exp)
    layer = _get_layer_or_404(conn, exp["layer_id"])

    tmp = store.stage(f"replace_{file.filename or 'file'}")
    with open(tmp, "wb") as out:
        shutil.copyfileobj(file.file, out)

    try:
        rgba = load_rgba(tmp)
        has_alpha = bool(rgba[..., 3].min() < 255)  # 完全不透明でなければ「透過済み」とみなす
        from core import importers
        new_asset_id = importers.import_image(tmp)
    finally:
        tmp.unlink(missing_ok=True)

    new_matte_mode = "skip" if has_alpha else exp["matte_mode"]
    with db.write_lock():
        conn.execute(
            "UPDATE exposures SET asset_id = ?, frame_id = 'f0000', matte_mode = ? "
            "WHERE id = ?",
            (new_asset_id, new_matte_mode, exposure_id),
        )
        _touch_composition(conn, layer["comp_id"])
        conn.commit()
    return _layer_out(conn, _get_layer_or_404(conn, exp["layer_id"]))
