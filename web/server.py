"""FastAPI アプリ。

M0 時点では「最小プレイヤー」に必要な読み取り専用エンドポイントのみを持つ。
§4 の編集系フルセット(POST/PUT/PATCH)は M1 以降で routes_edit.py 等に実装する。
このモジュールは②素材編集の起動条件（APIキー不要）を満たす: ここでは生成API
クライアント(core/ark.py, core/gptimage.py)を一切 import しない。
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from core import db, store
from web.routes_assets import router as assets_router
from web.routes_edit import router as edit_router
from web.routes_matte import router as matte_router

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "web" / "static"
DATA_ROOT = ROOT / "data"

app = FastAPI(title="SpriteSheet Studio")
app.include_router(assets_router)
app.include_router(edit_router)
app.include_router(matte_router)


@app.on_event("startup")
def _startup() -> None:
    store.init(DATA_ROOT)
    db.connect(DATA_ROOT / "studio.db")
    pending = store.recover_pending()
    if pending:
        # M0 時点ではログ出力のみ。復旧UIはM1で作る。
        dests = [p["dest_rel"] for p in pending]
        print(f"[startup] pending file recovery needed for: {dests}")


@app.get("/api/health")
def health():
    from tools import doctor  # 生成APIとは無関係。遅延importは他モジュールと歩調を合わせるため
    results = doctor.run_all()
    ok = all(r.get("ok") for r in results.values())
    return {"ok": ok, "checks": results}


@app.get("/api/files/{rel_path:path}")
def get_file(rel_path: str):
    if ".." in Path(rel_path).parts:
        raise HTTPException(
            status_code=400, detail={"code": "bad_path", "message": "invalid path"}
        )
    try:
        abs_path = store.to_abs(rel_path)
    except ValueError:
        raise HTTPException(
            status_code=400, detail={"code": "bad_path", "message": "invalid path"}
        )
    if not abs_path.exists() or not abs_path.is_file():
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": "file not found"}
        )
    return FileResponse(str(abs_path))


# 静的ファイル(index.html等)は最後にマウントする。上の @app.get 群が先に評価されるため
# /api/... と衝突しない。
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
