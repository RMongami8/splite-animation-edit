"""SQLite 接続とスキーマ。DB は1接続を共有し、書き込みは1つのロックで直列化する。

プラン §2-1 の DDL をそのまま SCHEMA に置く。schema_version が不一致なら起動を止める
（自動移行しない）。
"""
import shutil
import sqlite3
import threading
from pathlib import Path

SCHEMA_VERSION = "2"

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS assets (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  rel_path TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  width INTEGER, height INTEGER,
  n_frames INTEGER NOT NULL DEFAULT 1,
  tb_num INTEGER, tb_den INTEGER,
  rotation INTEGER NOT NULL DEFAULT 0,
  has_alpha INTEGER NOT NULL DEFAULT 0,
  source TEXT NOT NULL,
  attempt_id TEXT,
  meta_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS frames (
  asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
  frame_id TEXT NOT NULL,
  idx INTEGER NOT NULL,
  pts INTEGER,
  rel_path TEXT NOT NULL,
  width INTEGER NOT NULL, height INTEGER NOT NULL,
  has_alpha INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (asset_id, frame_id));

CREATE TABLE IF NOT EXISTS compositions (
  id TEXT PRIMARY KEY, name TEXT NOT NULL,
  canvas_w INTEGER NOT NULL, canvas_h INTEGER NOT NULL,
  tick_rate INTEGER NOT NULL DEFAULT 1000,
  total_ticks INTEGER NOT NULL DEFAULT 0,
  loop INTEGER NOT NULL DEFAULT 1,
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS layers (
  id TEXT PRIMARY KEY,
  comp_id TEXT NOT NULL REFERENCES compositions(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'normal',
  blend TEXT NOT NULL DEFAULT 'normal',
  opacity REAL NOT NULL DEFAULT 1.0,
  z INTEGER NOT NULL DEFAULT 0,
  start_ticks INTEGER NOT NULL DEFAULT 0,
  after_end TEXT NOT NULL DEFAULT 'hold',
  visible INTEGER NOT NULL DEFAULT 1,
  matte_json TEXT NOT NULL DEFAULT '{}',
  anchor_json TEXT NOT NULL DEFAULT '{}');

CREATE TABLE IF NOT EXISTS exposures (
  id TEXT PRIMARY KEY,
  layer_id TEXT NOT NULL REFERENCES layers(id) ON DELETE CASCADE,
  ord INTEGER NOT NULL,
  asset_id TEXT NOT NULL,
  frame_id TEXT NOT NULL,
  hold_ticks INTEGER NOT NULL,
  dx INTEGER NOT NULL DEFAULT 0, dy INTEGER NOT NULL DEFAULT 0,
  flip_x INTEGER NOT NULL DEFAULT 0,
  matte_mode TEXT NOT NULL DEFAULT 'inherit',
  scale REAL NOT NULL DEFAULT 1.0,
  matte_json TEXT NOT NULL DEFAULT '{}');
CREATE INDEX IF NOT EXISTS ix_exp_layer_ord ON exposures(layer_id, ord);

CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL,
  attempt_id TEXT,
  provider TEXT, region TEXT, api TEXT, model_id TEXT,
  external_task_id TEXT,
  request_json TEXT NOT NULL DEFAULT '{}',
  result_json TEXT NOT NULL DEFAULT '{}',
  error TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS exports (
  id TEXT PRIMARY KEY, comp_id TEXT NOT NULL,
  revision INTEGER NOT NULL, profile TEXT NOT NULL,
  rel_dir TEXT NOT NULL, status TEXT NOT NULL,
  report_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS derived_cache (
  key TEXT PRIMARY KEY, rel_path TEXT NOT NULL, created_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS pending_files (
  tmp_rel TEXT PRIMARY KEY, dest_rel TEXT NOT NULL,
  job_id TEXT, created_at TEXT NOT NULL);
"""

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None
_db_path: Path | None = None


class SchemaVersionMismatch(RuntimeError):
    pass


def connect(db_path: Path) -> sqlite3.Connection:
    """DB に接続しスキーマを適用する。以後 get_conn() が同じ接続を返す。

    プロセス内で1接続のみを保持する（複数呼び出しは既存接続を返す）。
    """
    global _conn, _db_path
    with _lock:
        if _conn is not None:
            return _conn
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        cur = conn.execute("SELECT value FROM meta WHERE key='schema_version'")
        row = cur.fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES ('schema_version', ?)",
                (SCHEMA_VERSION,),
            )
            conn.commit()
        elif row["value"] == "1" and SCHEMA_VERSION == "2":
            _migrate_v1_to_v2(conn, db_path)
        elif row["value"] != SCHEMA_VERSION:
            conn.close()
            raise SchemaVersionMismatch(
                f"DB schema_version={row['value']!r} but code expects "
                f"{SCHEMA_VERSION!r}. 自動移行はしない。data/studio.db を"
                f"確認し、必要なら移行スクリプトを書くかDBを作り直すこと。"
            )
        _conn = conn
        _db_path = db_path
        return conn


def _migrate_v1_to_v2(conn: sqlite3.Connection, db_path: Path) -> None:
    """v1 -> v2: exposures.scale を追加する唯一の明示移行(docs/decisions.md 参照)。

    移行前に DB を studio.v1.bak として複製する。倍率は画像中心基準で、既存行は 1.0。
    """
    conn.commit()
    bak = db_path.with_name(db_path.stem + ".v1.bak")
    if not bak.exists():
        conn.execute("PRAGMA wal_checkpoint(FULL)")
        shutil.copy2(db_path, bak)
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(exposures)").fetchall()]
    if "scale" not in cols:
        conn.execute("ALTER TABLE exposures ADD COLUMN scale REAL NOT NULL DEFAULT 1.0")
    conn.execute("UPDATE meta SET value = '2' WHERE key = 'schema_version'")
    conn.commit()


def get_conn() -> sqlite3.Connection:
    if _conn is None:
        raise RuntimeError("db not connected; call connect(db_path) first")
    return _conn


def write_lock():
    """書き込みを直列化するためのロック。with db.write_lock(): ... で使う。"""
    return _lock


def reset_for_tests() -> None:
    """テスト専用: プロセス内のグローバル接続を閉じてクリアする。"""
    global _conn, _db_path
    with _lock:
        if _conn is not None:
            _conn.close()
        _conn = None
        _db_path = None
