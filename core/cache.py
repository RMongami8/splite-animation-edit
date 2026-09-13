"""派生キャッシュ（プラン §2, cache.py 契約準拠）。

規則: ローカル派生処理は同条件なら再利用する。attempt_id は生成履歴(jobs/assets)側に
持たせ、派生キャッシュキーには含めない。「もう一度生成」は新しい attempt_id の新規
Asset を作る操作であり、このキャッシュの対象外（呼び出し側が新規計算として扱う）。
"""
import json
from datetime import datetime, timezone

from core import db


def derived_key(input_hash: str, settings: dict, processor_version: str) -> str:
    """派生キャッシュキーを作る。settings はキーソートした JSON にして安定させる。"""
    settings_str = json.dumps(settings, sort_keys=True, ensure_ascii=False)
    return f"{input_hash}:{processor_version}:{settings_str}"


def lookup(key: str) -> str | None:
    conn = db.get_conn()
    row = conn.execute(
        "SELECT rel_path FROM derived_cache WHERE key = ?", (key,)
    ).fetchone()
    return row["rel_path"] if row else None


def put(key: str, rel_path: str) -> None:
    conn = db.get_conn()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with db.write_lock():
        conn.execute(
            "INSERT INTO derived_cache(key, rel_path, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET rel_path = excluded.rel_path, "
            "created_at = excluded.created_at",
            (key, rel_path, now),
        )
        conn.commit()
