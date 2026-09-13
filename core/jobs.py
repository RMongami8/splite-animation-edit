"""ジョブの永続化と通知（プラン §2, §11 準拠）。

規則:
- SSE は通知専用。状態の真実は jobs テーブル（ブラウザ再読み込みで復元できる）。
- 応答不明な生成POSTを再送しない。external_task_id があれば状態確認から再開する。
"""
import json
import queue
import threading
from datetime import datetime, timezone
from typing import Iterator

from core import db
from core.ids import new_id

_subscribers: dict[str, list[queue.Queue]] = {}
_subs_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def create(kind: str, request: dict, attempt_id: str | None = None,
           provider: str | None = None, region: str | None = None,
           api: str | None = None, model_id: str | None = None) -> str:
    """新規ジョブを作成し job_id を返す。status='queued' で始まる。"""
    job_id = new_id("job")
    conn = db.get_conn()
    now = _now_iso()
    with db.write_lock():
        conn.execute(
            "INSERT INTO jobs(id, kind, status, attempt_id, provider, region, api, "
            "model_id, external_task_id, request_json, result_json, error, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (job_id, kind, "queued", attempt_id, provider, region, api, model_id,
             None, json.dumps(request, ensure_ascii=False), "{}", None, now, now),
        )
        conn.commit()
    return job_id


def _update(job_id: str, **fields) -> None:
    conn = db.get_conn()
    fields["updated_at"] = _now_iso()
    cols = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [job_id]
    with db.write_lock():
        conn.execute(f"UPDATE jobs SET {cols} WHERE id = ?", values)
        conn.commit()
    _notify(job_id)


def set_running(job_id: str, external_task_id: str | None = None) -> None:
    _update(job_id, status="running", external_task_id=external_task_id)


def succeed(job_id: str, result: dict) -> None:
    _update(job_id, status="succeeded", result_json=json.dumps(result, ensure_ascii=False))


def fail(job_id: str, error: str) -> None:
    _update(job_id, status="failed", error=error)


def get(job_id: str) -> dict | None:
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def resumable() -> list[dict]:
    """status が queued/running かつ external_task_id を持つジョブ一覧。
    起動時にこれを見て、生成APIの状態確認から再開する（再送はしない）。
    """
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT * FROM jobs WHERE status IN ('queued', 'running') "
        "AND external_task_id IS NOT NULL"
    ).fetchall()
    return [dict(r) for r in rows]


def _notify(job_id: str) -> None:
    with _subs_lock:
        subs = list(_subscribers.get(job_id, []))
    if not subs:
        return
    job = get(job_id)
    if job is None:
        return
    payload = json.dumps({"status": job["status"], "error": job["error"]}, ensure_ascii=False)
    for q in subs:
        q.put(payload)


def subscribe(job_id: str) -> Iterator[str]:
    """SSE通知専用ジェネレータ。状態の真実は jobs テーブルであり、これは通知のみ。

    現在状態を1回yieldしたあと、succeeded/failed になるまで変化を流し続ける。
    """
    job = get(job_id)
    if job is None:
        return
    q: queue.Queue = queue.Queue()
    with _subs_lock:
        _subscribers.setdefault(job_id, []).append(q)
    try:
        current = json.dumps({"status": job["status"], "error": job["error"]}, ensure_ascii=False)
        yield f"data: {current}\n\n"
        if job["status"] in ("succeeded", "failed"):
            return
        while True:
            payload = q.get()
            yield f"data: {payload}\n\n"
            if json.loads(payload)["status"] in ("succeeded", "failed"):
                return
    finally:
        with _subs_lock:
            lst = _subscribers.get(job_id, [])
            if q in lst:
                lst.remove(q)
