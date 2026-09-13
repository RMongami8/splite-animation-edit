"""透過処理(マット)API の受け口。プラン §4 の POST /api/comps/{id}/matte。

外部APIプロバイダーは未接続(core/matte_api.py 参照)。対象の検証までは行い、
プロバイダーが無ければ 501 matte_provider_not_configured を返す。
"""
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core import db, matte_api

router = APIRouter()


def _err(status: int, code: str, message: str):
    raise HTTPException(status_code=status, detail={"code": code, "message": message})


class MatteBody(BaseModel):
    exposure_ids: list[str]
    provider: str = "auto"
    mode: Literal["preview", "apply"] = "preview"
    options: dict = {}


@router.get("/api/matte/providers")
def list_providers():
    return {"providers": matte_api.available_providers()}


@router.post("/api/comps/{comp_id}/matte")
def apply_matte(comp_id: str, body: MatteBody):
    conn = db.get_conn()
    if conn.execute("SELECT 1 FROM compositions WHERE id = ?", (comp_id,)).fetchone() is None:
        _err(404, "not_found", "composition not found")
    ids = list(dict.fromkeys(body.exposure_ids))
    if not ids:
        _err(400, "no_targets", "exposure_ids must not be empty")
    marks = ",".join("?" for _ in ids)
    n = conn.execute(
        f"SELECT COUNT(*) FROM exposures e JOIN layers l ON l.id = e.layer_id "
        f"WHERE l.comp_id = ? AND e.id IN ({marks})",
        [comp_id, *ids],
    ).fetchone()[0]
    if n != len(ids):
        _err(400, "bad_targets", "some exposure_ids do not belong to this composition")
    provider = matte_api.get_provider(body.provider)
    if provider is None:
        _err(501, "matte_provider_not_configured",
             "no background-removal API provider is configured yet")
    # プロバイダー接続後にここで反映処理を行う(手順は core/matte_api.py の docstring)
    _err(501, "not_implemented", "applying provider results is scheduled for later")
