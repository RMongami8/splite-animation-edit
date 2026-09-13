"""M0 自己検証: core/composite.py (Python) と web/static/js/composite.js (Node) の
出力が許容誤差内で一致するかをクロス言語で検証する（プラン §6 準拠）。

一致基準: 最大差 <= 2/255、平均差 <= 0.5/255。時間・座標・コマ順は対象外
（このテストは合成式(blend_normal/blend_add)のみを対象にする）。

使い方: python -m tools.selftest_parity
結果は docs/parity.md に追記される。
"""
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

from core import composite

ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = ROOT / "tools"
DOCS_DIR = ROOT / "docs"

MAX_DIFF_LIMIT = 2
MEAN_DIFF_LIMIT = 0.5


def _make_test_arrays(w: int, h: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    dst = rng.integers(0, 256, size=(h, w, 4), dtype=np.uint8)
    src = rng.integers(0, 256, size=(h, w, 4), dtype=np.uint8)
    # 境界値も混ぜる: 完全不透明・完全透明・半透明のピクセルを混在させる
    src[0, 0, 3] = 0
    src[0, 1, 3] = 255
    src[0, 2, 3] = 128
    return dst, src


def _run_node_driver(dst: np.ndarray, src: np.ndarray, opacity: float,
                      work_dir: Path) -> tuple[np.ndarray, np.ndarray]:
    h, w = dst.shape[:2]
    dst_path = work_dir / "dst.bin"
    src_path = work_dir / "src.bin"
    dst_path.write_bytes(dst.tobytes())
    src_path.write_bytes(src.tobytes())

    node = shutil.which("node")
    if node is None:
        raise RuntimeError("node コマンドが見つからない。Node.js がインストールされているか確認すること。")

    driver = TOOLS_DIR / "_composite_driver.cjs"
    result = subprocess.run(
        [node, str(driver), str(dst_path), str(src_path), str(w), str(h),
         str(opacity), str(work_dir)],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"node driver failed: {result.stderr}")

    normal_js = np.frombuffer(
        (work_dir / "normal_js.bin").read_bytes(), dtype=np.uint8
    ).reshape(h, w, 4)
    add_js = np.frombuffer(
        (work_dir / "add_js.bin").read_bytes(), dtype=np.uint8
    ).reshape(h, w, 4)
    return normal_js, add_js


def _compare(name: str, py_out: np.ndarray, js_out: np.ndarray) -> dict:
    diff = np.abs(py_out.astype(np.int16) - js_out.astype(np.int16))
    max_diff = int(diff.max())
    mean_diff = float(diff.mean())
    ok = max_diff <= MAX_DIFF_LIMIT and mean_diff <= MEAN_DIFF_LIMIT
    return {"name": name, "max_diff": max_diff, "mean_diff": mean_diff, "ok": ok}


def run() -> list[dict]:
    work_dir = ROOT / "data" / "_parity_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    reports = []
    try:
        for i, (w, h, opacity) in enumerate([
            (16, 16, 1.0), (16, 16, 0.5), (8, 8, 0.0), (32, 24, 0.75),
        ]):
            dst, src = _make_test_arrays(w, h, seed=1000 + i)
            py_normal = composite.blend_normal(dst, src, opacity)
            py_add = composite.blend_add(dst, src, opacity)
            js_normal, js_add = _run_node_driver(dst, src, opacity, work_dir)

            reports.append(_compare(f"blend_normal w{w}h{h}op{opacity}", py_normal, js_normal))
            reports.append(_compare(f"blend_add w{w}h{h}op{opacity}", py_add, js_add))
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
    return reports


def write_report(reports: list[dict]) -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    path = DOCS_DIR / "parity.md"
    lines = ["# 合成式パリティ検証 (Python core/composite.py vs JS composite.js)", ""]
    lines.append(f"許容誤差: 最大差 <= {MAX_DIFF_LIMIT}/255, 平均差 <= {MEAN_DIFF_LIMIT}/255")
    lines.append("")
    lines.append("| ケース | 最大差 | 平均差 | 判定 |")
    lines.append("|---|---|---|---|")
    for r in reports:
        mark = "PASS" if r["ok"] else "FAIL"
        lines.append(f"| {r['name']} | {r['max_diff']} | {r['mean_diff']:.4f} | {mark} |")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main() -> int:
    reports = run()
    write_report(reports)
    all_ok = all(r["ok"] for r in reports)
    for r in reports:
        mark = "PASS" if r["ok"] else "FAIL"
        print(f"[{mark}] {r['name']}: max_diff={r['max_diff']} mean_diff={r['mean_diff']:.4f}")
    print("selftest_parity:", "PASS" if all_ok else "FAIL")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
