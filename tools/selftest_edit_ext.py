"""自己検証: タイムライン編集拡張(docs/decisions.md「タイムライン編集拡張」)。

- schema v1 -> v2 移行(exposures.scale 追加・バックアップ作成・既存行 1.0)
- core/keyframes.frame_diff_scores
- レイヤー追加の frame_indices / hold_mode(source で尺を保つ、fixed で一定)
- exposure の scale の PUT/PATCH 往復と範囲検証
- POST /api/comps/{id}/matte の受け口(501 / 他Compのコマは 400)

make_dummy のフィクスチャ(cp_dummy, 64x64・8コマ)を使い、作ったレイヤーは消して片付ける。
使い方: python -m tools.selftest_edit_ext
"""
import shutil
import sqlite3
import sys
from pathlib import Path

from fastapi import HTTPException
from pydantic import ValidationError

from core import db, keyframes, store
from tools import make_dummy

ROOT = Path(__file__).resolve().parent.parent


def _check_migration(checks: list[dict]) -> None:
    tmp = ROOT / "data" / "_selftest_edit_ext"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    path = tmp / "studio.db"
    v1_schema = db.SCHEMA.replace("  scale REAL NOT NULL DEFAULT 1.0,\n", "")
    raw = sqlite3.connect(str(path))
    raw.executescript(v1_schema)
    raw.execute("PRAGMA foreign_keys=OFF")  # 親行なしの exposure だけで移行を確かめる
    raw.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '1')")
    raw.execute(
        "INSERT INTO exposures(id, layer_id, ord, asset_id, frame_id, hold_ticks) "
        "VALUES ('ex_old', 'ly_x', 0, 'as_x', 'f0000', 100)")
    raw.commit()
    raw.close()

    db.reset_for_tests()
    try:
        conn = db.connect(path)
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(exposures)")]
        ver = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
        old = conn.execute("SELECT scale FROM exposures WHERE id='ex_old'").fetchone()[0]
        checks.append({
            "name": "schema v1 DB migrates to v2 (scale column, backup, existing rows=1.0)",
            "ok": "scale" in cols and ver == "2" and old == 1.0
            and (tmp / "studio.v1.bak").exists(),
            "detail": f"ver={ver} scale={old}",
        })
    finally:
        db.reset_for_tests()
        shutil.rmtree(tmp, ignore_errors=True)


def run() -> list[dict]:
    checks: list[dict] = []
    _check_migration(checks)

    make_dummy.run()  # store.init + db.connect(data/studio.db) も行う
    conn = db.get_conn()
    from web import routes_edit, routes_matte

    paths = [store.to_abs(r["rel_path"]) for r in conn.execute(
        "SELECT rel_path FROM frames WHERE asset_id=? ORDER BY idx",
        (make_dummy.ASSET_CHAR,))]
    scores = keyframes.frame_diff_scores(paths)
    same = keyframes.frame_diff_scores([paths[0], paths[0]])
    checks.append({
        "name": "frame_diff_scores: one score per frame, first=1.0, identical frame=0",
        "ok": len(scores) == 8 and scores[0] == 1.0 and same[1] == 0.0
        and all(0 <= s <= 1 for s in scores),
    })

    created = []
    try:
        def mk(**kw):
            body = routes_edit.CreateLayerBody(
                name="_selftest", asset_id=make_dummy.ASSET_CHAR, z=99, **kw)
            ly = routes_edit.create_layer(make_dummy.COMP_ID, body)
            created.append(ly["id"])
            return [e["hold_ticks"] for e in ly["exposures"]], ly

        full, _ = mk()
        picked, _ = mk(frame_indices=[0, 3, 6])
        fixed, ly_fixed = mk(frame_indices=[1, 2], hold_mode="fixed", fixed_hold_ticks=80)
        checks.append({
            "name": "frame_indices + hold_mode=source keeps the total duration",
            "ok": len(picked) == 3 and sum(picked) == sum(full),
            "detail": f"full={sum(full)} picked={picked}",
        })
        checks.append({
            "name": "hold_mode=fixed uses fixed_hold_ticks for every exposure",
            "ok": fixed == [80, 80] and [e["frame_id"] for e in ly_fixed["exposures"]]
            == ["f0001", "f0002"],
        })

        exps = [routes_edit.ExposureIn(
            id=e["id"], asset_id=e["asset_id"], frame_id=e["frame_id"],
            hold_ticks=e["hold_ticks"], scale=1.5) for e in ly_fixed["exposures"]]
        out = routes_edit.replace_exposures(
            ly_fixed["id"], routes_edit.PutExposuresBody(exposures=exps))
        eid = out["exposures"][0]["id"]
        out2 = routes_edit.patch_exposure(eid, routes_edit.PatchExposureBody(scale=0.5))
        try:
            routes_edit.PatchExposureBody(scale=9)
            rejected = False
        except ValidationError:
            rejected = True
        checks.append({
            "name": "exposure scale round-trips via PUT/PATCH and rejects out-of-range",
            "ok": [e["scale"] for e in out["exposures"]] == [1.5, 1.5]
            and out2["exposures"][0]["scale"] == 0.5 and rejected,
        })

        def matte_status(ids):
            try:
                routes_matte.apply_matte(make_dummy.COMP_ID, routes_matte.MatteBody(exposure_ids=ids))
            except HTTPException as e:
                return e.status_code, e.detail["code"]
            return 200, None
        st_ok = matte_status([eid])
        st_bad = matte_status(["ex_not_in_comp"])
        checks.append({
            "name": "matte endpoint: 501 without provider, 400 for foreign exposure ids",
            "ok": st_ok == (501, "matte_provider_not_configured") and st_bad[0] == 400,
            "detail": f"{st_ok} {st_bad}",
        })
    finally:
        for lid in created:
            routes_edit.delete_layer(lid)

    return checks


def main() -> int:
    checks = run()
    all_ok = all(c["ok"] for c in checks)
    for c in checks:
        mark = "PASS" if c["ok"] else "FAIL"
        extra = f" ({c['detail']})" if "detail" in c else ""
        print(f"[{mark}] {c['name']}{extra}")
    print("selftest_edit_ext:", "PASS" if all_ok else "FAIL")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
