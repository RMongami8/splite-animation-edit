"""時間モデル（プラン §3, モジュール契約 core/timeline.py 準拠）。

規則:
- 丸めは floor(x + 0.5) のみ。round() は使わない（偶数丸めで結果がJS側とずれるため）。
- 区間は [start, end) の半開区間。end_i == start_{i+1}。
- tick_rate は 1000 固定。
- 元PTSは有理数のまま保持し、tick への変換はここでのみ行う。
"""
from fractions import Fraction


def _floor_half(x: Fraction) -> int:
    """floor(x + 0.5) を厳密に計算する（Fraction のまま。float を経由しない）。"""
    return (x + Fraction(1, 2)).__floor__()


def pts_to_ticks(pts: int, tb_num: int, tb_den: int, tick_rate: int) -> int:
    """整数PTS -> 編集tick。

    PTS の実時間 = pts * tb_num / tb_den 秒。tick = 実時間 * tick_rate。
    Fraction で正確に計算し、最後だけ floor(x+0.5) で丸める。
    """
    seconds = Fraction(pts * tb_num, tb_den)
    ticks = seconds * tick_rate
    return _floor_half(ticks)


def uniform_boundaries(n: int) -> list[Fraction]:
    """Fraction(i, n) を n 個（0/n, 1/n, ..., (n-1)/n）。

    distribute_holds と組み合わせると 4000ms を12枚に分けて 333/334ms 配分になる。
    """
    if n <= 0:
        raise ValueError("n must be positive")
    return [Fraction(i, n) for i in range(n)]


def distribute_holds(total_ticks: int, boundaries: list[Fraction]) -> list[int]:
    """boundaries(昇順, 先頭0, 0.0-1.0の正規化開始位置) から各区間の hold を計算する。

    累積境界を floor(b*total + 0.5) で求め、隣接差分を hold にする。
    戻り値の合計は必ず total_ticks に一致する（端数はここで吸収される）。
    """
    if not boundaries:
        raise ValueError("boundaries must not be empty")
    if boundaries[0] != 0:
        raise ValueError("boundaries must start at 0")
    # 各境界を tick 位置に変換（末尾に total_ticks を追加して n+1 点にする）
    cum = [_floor_half(b * total_ticks) for b in boundaries]
    cum.append(total_ticks)
    holds = [cum[i + 1] - cum[i] for i in range(len(cum) - 1)]
    assert sum(holds) == total_ticks, (
        f"hold distribution bug: sum={sum(holds)} != total={total_ticks}"
    )
    return holds


def exposure_spans(holds: list[int], start_ticks: int = 0) -> list[tuple[int, int]]:
    """hold のリスト -> [start, end) の半開区間リスト。end_i == start_{i+1} を保証。"""
    spans = []
    t = start_ticks
    for h in holds:
        if h < 0:
            raise ValueError(f"negative hold: {h}")
        spans.append((t, t + h))
        t += h
    return spans


def layer_frame_at(spans: list[tuple[int, int]], t: int, after_end: str,
                    loop_len: int) -> int | None:
    """時刻 t における Exposure index を返す。

    after_end: "loop" | "hold" | "hide"
    loop_len: レイヤーの1周期の長さ（tick）。spans[-1][1] - spans[0][0] と一致するのが通常。
    範囲外(t が終端後)の扱いは after_end に従う。t が開始前(spans[0][0] より前)なら None。
    """
    if not spans:
        return None
    start0 = spans[0][0]
    end_last = spans[-1][1]
    if t < start0:
        return None
    if t >= end_last:
        if after_end == "hide":
            return None
        if after_end == "hold":
            return len(spans) - 1
        if after_end == "loop":
            if loop_len <= 0:
                return len(spans) - 1
            # ループ後の相対時刻に変換してから探索
            rel = start0 + ((t - start0) % loop_len)
            return _find_span_index(spans, rel)
        raise ValueError(f"unknown after_end: {after_end!r}")
    return _find_span_index(spans, t)


def _find_span_index(spans: list[tuple[int, int]], t: int) -> int | None:
    """線形探索（コマ数は少数想定のため二分探索を要しない）。"""
    for i, (s, e) in enumerate(spans):
        if s <= t < e:
            return i
    # 端数誤差でわずかに外れた場合、最後の区間に含める
    if spans and t == spans[-1][1]:
        return len(spans) - 1
    return None


def merge_switch_times(layers: list[list[tuple[int, int]]]) -> list[int]:
    """可変時間出力用。全レイヤーの切り替え時刻(各spanのstart)を統合し昇順ユニーク化。"""
    times: set[int] = set()
    for spans in layers:
        for s, e in spans:
            times.add(s)
            times.add(e)
    return sorted(times)


def total_ticks_of(layers: list[list[tuple[int, int]]]) -> int:
    """Composition 全体尺。最後のコマの終了時刻を含む（全レイヤーの最大 end）。"""
    ends = [spans[-1][1] for spans in layers if spans]
    if not ends:
        return 0
    return max(ends)
