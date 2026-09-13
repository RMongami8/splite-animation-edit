"""環境検査（プラン §11 の tools/doctor.py 契約準拠）。M0 の最初に作るツール。

検査項目:
1. Python バージョン、sys.getdefaultencoding()
2. import av の成否 -> 成功なら PyAV 経路、失敗なら ffmpeg 経路を記録
3. imageio_ffmpeg.get_ffmpeg_exe() の存在と -version 実行
4. SQLite の journal_mode=WAL が有効になるか
5. data/ 配下の書き込みと os.replace() の動作
6. Pillow の PNG 透過保存・再読込でアルファが保たれるか
7. 結果を docs/versions.md に追記（バージョン文字列以外は出力しない）

使い方: python -m tools.doctor
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "docs"


def check_python() -> dict:
    return {
        "ok": True,
        "version": sys.version.split()[0],
        "encoding": sys.getdefaultencoding(),
    }


def check_pyav() -> dict:
    try:
        import av  # noqa: F401
        return {"ok": True, "backend": "pyav", "version": av.__version__}
    except Exception as e:
        return {"ok": False, "backend": "ffmpeg_fallback", "error": str(e)}


def check_ffmpeg() -> dict:
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:
        return {"ok": False, "error": f"imageio_ffmpeg unavailable: {e}"}
    if not Path(exe).exists():
        return {"ok": False, "error": f"ffmpeg exe not found at {exe}"}
    result = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=15)
    if result.returncode != 0:
        return {"ok": False, "error": f"ffmpeg -version failed: {result.stderr[:200]}"}
    first_line = result.stdout.splitlines()[0] if result.stdout else "?"
    return {"ok": True, "exe": exe, "version_line": first_line}


def check_sqlite_wal() -> dict:
    test_db = ROOT / "data" / "_doctor_test.sqlite"
    test_db.parent.mkdir(parents=True, exist_ok=True)
    if test_db.exists():
        test_db.unlink()
    import sqlite3
    conn = sqlite3.connect(str(test_db))
    mode = conn.execute("PRAGMA journal_mode=WAL;").fetchone()[0]
    conn.close()
    test_db.unlink(missing_ok=True)
    for ext in ("-wal", "-shm"):
        p = Path(str(test_db) + ext)
        if p.exists():
            p.unlink()
    return {"ok": mode.lower() == "wal", "mode": mode}


def check_replace() -> dict:
    tmp_dir = ROOT / "data" / "_doctor_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_dir / "a.txt"
    dst = tmp_dir / "b.txt"
    src.write_text("new", encoding="utf-8")
    dst.write_text("old", encoding="utf-8")  # 既存ファイルがある状態で置換できるか
    try:
        os.replace(str(src), str(dst))
        ok = dst.read_text(encoding="utf-8") == "new" and not src.exists()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return {"ok": ok}


def check_png_alpha() -> dict:
    from core.imageio_ import save_png, load_rgba
    p = ROOT / "data" / "_doctor_alpha.png"
    p.parent.mkdir(parents=True, exist_ok=True)
    rgba = np.zeros((4, 4, 4), np.uint8)
    rgba[..., 0] = 200
    rgba[..., 3] = 77
    save_png(p, rgba)
    back = load_rgba(p)
    ok = bool(np.array_equal(rgba, back))
    p.unlink(missing_ok=True)
    return {"ok": ok}


def run_all() -> dict:
    return {
        "python": check_python(),
        "pyav": check_pyav(),
        "ffmpeg": check_ffmpeg(),
        "sqlite_wal": check_sqlite_wal(),
        "os_replace": check_replace(),
        "png_alpha": check_png_alpha(),
    }


def write_report(results: dict) -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    path = DOCS_DIR / "versions.md"
    lines = ["# 環境検査結果 (tools/doctor.py)", ""]
    for name, r in results.items():
        mark = "OK" if r.get("ok") else "NG"
        detail = {k: v for k, v in r.items() if k != "ok"}
        lines.append(f"- **{name}**: {mark} — {detail}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main() -> int:
    results = run_all()
    write_report(results)
    all_ok = all(r.get("ok") for r in results.values())
    for name, r in results.items():
        mark = "OK" if r.get("ok") else "NG"
        print(f"[{mark}] {name}")
        if not r.get("ok"):
            print(f"       -> {r}")
    print("doctor:", "PASS" if all_ok else "FAIL")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
