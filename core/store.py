"""ファイル配置と原子的コミット。

規則（プラン §0, §2 準拠）:
- ファイル置換は os.replace()（os.rename は Windows で既存ファイルがあると失敗する）
- テキスト I/O は encoding="utf-8"、json.dump(..., ensure_ascii=False)
- DB に入れるパスは常にプロジェクト相対の posix 文字列
- originals/ は追記のみ

確定順序: tmp/ に保存 -> 検査 -> pending_files 登録 -> os.replace で確定配置
-> DB 登録(1トランザクション) -> pending_files から削除。
"""
import hashlib
import json
import os
import secrets
from pathlib import Path

from core import db

_data_root: Path | None = None


def init(data_root: Path) -> None:
    """data ルートを設定し、必要なサブディレクトリを作る。"""
    global _data_root
    data_root = Path(data_root)
    for sub in ("originals", "derived/frames", "derived/matte", "derived/thumbs",
                "exports", "tmp", "projects"):
        (data_root / sub).mkdir(parents=True, exist_ok=True)
    _data_root = data_root


def root() -> Path:
    if _data_root is None:
        raise RuntimeError("store not initialized; call store.init(data_root) first")
    return _data_root


def to_rel(abs_path: Path) -> str:
    """絶対パス -> data root からの相対 posix 文字列（DB 格納用）。"""
    return Path(abs_path).resolve().relative_to(root().resolve()).as_posix()


def to_abs(rel_path: str) -> Path:
    """DB 格納の相対 posix 文字列 -> 絶対パス。".." を含む場合は拒否する。"""
    if ".." in Path(rel_path).parts:
        raise ValueError(f"unsafe rel_path: {rel_path!r}")
    return root() / rel_path


def stage(tmp_name: str) -> Path:
    """data/tmp に作業パスを作る。衝突を避けるため乱数を挟む。"""
    unique = f"{secrets.token_hex(4)}_{tmp_name}"
    p = root() / "tmp" / unique
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def commit(tmp: Path, dest_rel: str, job_id: str | None = None) -> str:
    """tmp のファイルを検査してから dest_rel (data root 相対) へ確定配置する。

    検査は「ファイルが存在し、サイズ > 0」の最小限のみ。デコード可能性の検査は
    呼び出し側（importers 等）が commit の前に済ませておく。戻り値は dest_rel。
    """
    tmp = Path(tmp)
    if not tmp.exists() or tmp.stat().st_size == 0:
        raise ValueError(f"commit source invalid or empty: {tmp}")
    dest_abs = to_abs(dest_rel)
    dest_abs.parent.mkdir(parents=True, exist_ok=True)

    conn = db.get_conn()
    now = _now_iso()
    with db.write_lock():
        conn.execute(
            "INSERT INTO pending_files(tmp_rel, dest_rel, job_id, created_at) "
            "VALUES (?, ?, ?, ?)",
            (to_rel(tmp), dest_rel, job_id, now),
        )
        conn.commit()
        os.replace(str(tmp), str(dest_abs))
        conn.execute("DELETE FROM pending_files WHERE dest_rel = ?", (dest_rel,))
        conn.commit()
    return dest_rel


def recover_pending() -> list[dict]:
    """起動時に呼ぶ。commit 途中でクラッシュした形跡があれば一覧で返す。"""
    conn = db.get_conn()
    rows = conn.execute("SELECT * FROM pending_files").fetchall()
    result = []
    for r in rows:
        d = dict(r)
        tmp_abs = to_abs(d["tmp_rel"])
        dest_abs = to_abs(d["dest_rel"])
        d["tmp_exists"] = tmp_abs.exists()
        d["dest_exists"] = dest_abs.exists()
        result.append(d)
    return result


def clear_pending(dest_rel: str) -> None:
    """復旧処理が完了した pending_files 行を消す。"""
    conn = db.get_conn()
    with db.write_lock():
        conn.execute("DELETE FROM pending_files WHERE dest_rel = ?", (dest_rel,))
        conn.commit()


def read_json(rel: str) -> dict:
    p = to_abs(rel)
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json_atomic(rel: str, obj: dict) -> None:
    """一時ファイルへ書いてから os.replace で確定する原子的 JSON 書き込み。"""
    dest_abs = to_abs(rel)
    dest_abs.parent.mkdir(parents=True, exist_ok=True)
    tmp = stage(Path(rel).name + ".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(str(tmp), str(dest_abs))


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
