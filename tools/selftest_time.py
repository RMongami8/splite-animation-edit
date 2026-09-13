"""自己検証: 時間モデル（プラン §3, §12 準拠）。

検証内容:
1. tools.make_dummy が作った Composition (8コマ/レイヤー, 4000ms) を DB から読み、
   各レイヤーの hold 合計が total_ticks と一致し、最後のコマの終了時刻が
   total_ticks に一致する(= 最後のコマの hold が尺に含まれる)ことを確認する。
2. 4000ms を12枚に分配した場合に合計が必ず4000msになる(333/334混在)ことを
   直接 core.timeline で検証する（plan の代表例）。
3. merge_switch_times / total_ticks_of / layer_frame_at の基本契約を確認する。
4. (M1) 実際に ffmpeg で生成した動画を core.video.probe() で実測PTSを取得し、
   core.timeline.pts_to_ticks() が正しい tick 値に変換できることを確認する
   （プラン §11 M1 完了条件「selftest_time が実動画でPASS」に対応）。

使い方: python -m tools.selftest_time
"""
import shutil
import subprocess
import sys
from pathlib import Path

from core import db, store
from core.timeline import (distribute_holds, exposure_spans, layer_frame_at,
                            merge_switch_times, pts_to_ticks, total_ticks_of,
                            uniform_boundaries)
from tools.make_dummy import COMP_ID, LAYER_CHAR, LAYER_FX

ROOT = Path(__file__).resolve().parent.parent


def _load_layer_spans(conn, layer_id: str) -> list[tuple[int, int]]:
    rows = conn.execute(
        "SELECT hold_ticks FROM exposures WHERE layer_id = ? ORDER BY ord",
        (layer_id,),
    ).fetchall()
    holds = [r["hold_ticks"] for r in rows]
    return exposure_spans(holds, 0)


def check_dummy_composition() -> list[dict]:
    store.init(ROOT / "data")
    conn = db.connect(ROOT / "data" / "studio.db")
    comp = conn.execute(
        "SELECT * FROM compositions WHERE id = ?", (COMP_ID,)
    ).fetchone()
    checks = []
    if comp is None:
        checks.append({"name": "dummy composition exists", "ok": False,
                        "detail": "run `python -m tools.make_dummy` first"})
        return checks
    total_ticks = comp["total_ticks"]
    checks.append({"name": "dummy composition exists", "ok": True})

    for name, layer_id in [("char", LAYER_CHAR), ("fx", LAYER_FX)]:
        spans = _load_layer_spans(conn, layer_id)
        span_sum = sum(e - s for s, e in spans)
        contiguous = all(spans[i][1] == spans[i + 1][0] for i in range(len(spans) - 1))
        last_end_ok = spans[-1][1] == total_ticks if spans else False
        checks.append({
            "name": f"layer[{name}] hold sum == total_ticks",
            "ok": span_sum == total_ticks,
            "detail": f"sum={span_sum} total={total_ticks}",
        })
        checks.append({
            "name": f"layer[{name}] spans contiguous ([start,end) end_i==start_i+1)",
            "ok": contiguous,
        })
        checks.append({
            # 最後のコマの hold が尺に含まれることの確認
            "name": f"layer[{name}] last exposure end == total_ticks (last hold included)",
            "ok": last_end_ok,
            "detail": f"last_end={spans[-1][1] if spans else None} total={total_ticks}",
        })
    return checks


def check_uneven_distribution() -> list[dict]:
    """plan の代表例: 4000ms を12枚に分配 -> 333/334 混在で合計4000ms。"""
    holds = distribute_holds(4000, uniform_boundaries(12))
    ok_sum = sum(holds) == 4000
    ok_values = set(holds) <= {333, 334}
    return [
        {"name": "distribute_holds(4000, 12) sum == 4000",
         "ok": ok_sum, "detail": f"holds={holds}"},
        {"name": "distribute_holds(4000, 12) values are 333/334 only",
         "ok": ok_values, "detail": f"unique={sorted(set(holds))}"},
    ]


def check_layer_frame_and_merge() -> list[dict]:
    checks = []
    layer_a = exposure_spans([1000, 1000, 1000, 1000], 0)
    layer_b = exposure_spans([500] * 8, 0)

    idx_mid = layer_frame_at(layer_a, 2500, "hold", 4000)
    checks.append({"name": "layer_frame_at mid-span lookup",
                    "ok": idx_mid == 2, "detail": f"idx={idx_mid}"})

    idx_hold = layer_frame_at(layer_a, 9999, "hold", 4000)
    idx_hide = layer_frame_at(layer_a, 9999, "hide", 4000)
    idx_loop = layer_frame_at(layer_a, 4000, "loop", 4000)
    checks.append({"name": "after_end=hold clamps to last exposure",
                    "ok": idx_hold == 3})
    checks.append({"name": "after_end=hide returns None past end",
                    "ok": idx_hide is None})
    checks.append({"name": "after_end=loop wraps to first exposure at boundary",
                    "ok": idx_loop == 0})

    merged = merge_switch_times([layer_a, layer_b])
    checks.append({"name": "merge_switch_times is sorted+unique",
                    "ok": merged == sorted(set(merged))})

    tot = total_ticks_of([layer_a, layer_b])
    checks.append({"name": "total_ticks_of == max end across layers",
                    "ok": tot == 4000, "detail": f"total={tot}"})
    return checks


def check_real_video_pts() -> list[dict]:
    """ffmpeg で 8fps・1秒・64x64 の実動画を生成し、core.video.probe() の実測PTSを
    core.timeline.pts_to_ticks() で ticks に変換した結果が正しいことを確認する。
    """
    from core import video

    checks = []
    work_dir = ROOT / "data" / "_selftest_time_video"
    work_dir.mkdir(parents=True, exist_ok=True)
    vid_path = work_dir / "test.mp4"
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        result = subprocess.run(
            [exe, "-hide_banner", "-y", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=8",
             "-t", "1", "-pix_fmt", "yuv420p", str(vid_path)],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            checks.append({"name": "generate test video with ffmpeg", "ok": False,
                            "detail": result.stderr[-500:]})
            return checks
        checks.append({"name": "generate test video with ffmpeg", "ok": True})

        info = video.probe(vid_path)
        checks.append({"name": "probe() decodes 8 frames from 1s@8fps video",
                        "ok": info["n_frames"] == 8, "detail": f"n_frames={info['n_frames']}"})

        tick_rate = 1000
        ticks = [pts_to_ticks(p, info["tb_num"], info["tb_den"], tick_rate)
                 for p in info["pts_list"]]
        expected = [round(i * 1000 / 8) for i in range(8)]  # 0,125,250,...,875
        # 丸め方式の差(floor(x+0.5) vs round)が出ても1ms以内なら許容する
        close_enough = all(abs(a - b) <= 1 for a, b in zip(ticks, expected))
        checks.append({
            "name": "pts_to_ticks() on real measured PTS matches expected 125ms steps",
            "ok": close_enough, "detail": f"ticks={ticks} expected~={expected}",
        })

        # 抽出したフレームのptsもprobe()のpts_listと一致することを確認
        extract_dir = work_dir / "frames"
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        extracted = video.extract_frames(vid_path, extract_dir)
        extracted_pts = [f["pts"] for f in extracted]
        checks.append({
            "name": "extract_frames() pts matches probe() pts_list",
            "ok": extracted_pts == info["pts_list"],
            "detail": f"extracted={extracted_pts} probed={info['pts_list']}",
        })
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
    return checks


def run() -> list[dict]:
    return (check_dummy_composition() + check_uneven_distribution()
            + check_layer_frame_and_merge() + check_real_video_pts())


def main() -> int:
    checks = run()
    all_ok = all(c["ok"] for c in checks)
    for c in checks:
        mark = "PASS" if c["ok"] else "FAIL"
        extra = f" ({c['detail']})" if "detail" in c else ""
        print(f"[{mark}] {c['name']}{extra}")
    print("selftest_time:", "PASS" if all_ok else "FAIL")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
