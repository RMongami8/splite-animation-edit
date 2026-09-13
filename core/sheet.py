"""シートパッキング（プラン §9 準拠）。

規則:
- 全コマ共通の倍率で縮小する。コマごとの自動フィットはしない。
- 縮小補間は box filter (PIL Image.BOX) に固定。
- セルは cell_wh 内で下辺中央アンカー(bottom-center)に配置する
  （既定 pivot [0.5, 1.0] = 足元中央、と対応させるため）。
"""
import numpy as np
from PIL import Image


def scale_to_cell(rgbas: list[np.ndarray], cell_wh: tuple[int, int]
                   ) -> tuple[list[np.ndarray], float]:
    """全フレーム中の最大 width/height が cell_wh に収まる、全コマ共通の倍率で縮小する。

    倍率は縮小のみ（拡大はしない。scale の上限は 1.0）。
    """
    if not rgbas:
        return [], 1.0
    cell_w, cell_h = cell_wh
    max_w = max(a.shape[1] for a in rgbas)
    max_h = max(a.shape[0] for a in rgbas)
    scale = min(cell_w / max_w, cell_h / max_h, 1.0)
    if scale >= 1.0:
        return [a.copy() for a in rgbas], 1.0

    scaled = []
    for a in rgbas:
        h, w = a.shape[:2]
        new_w = max(1, int(w * scale + 0.5))
        new_h = max(1, int(h * scale + 0.5))
        img = Image.fromarray(a, mode="RGBA").resize((new_w, new_h), Image.BOX)
        scaled.append(np.array(img))
    return scaled, scale


def build_grid(cells: list[np.ndarray], cols: int, cell_wh: tuple[int, int],
                padding: int, extrude: int, max_page: int
                ) -> tuple[list[np.ndarray], list[dict]]:
    """cells (各 <= cell_wh の RGBA, uint8) を cols 列のグリッドへ詰める。

    各セルは cell_wh の枠内で下辺中央アンカーに配置する。padding はセル間の余白(px)。
    extrude はセル境界のにじみ防止用に縁ピクセルを複製する幅(px)。
    ページ幅・高さが max_page を超える場合は自動でページ分割する（縦方向のみ分割。
    cols * cell_w が max_page を超える場合は呼び出し側の設定ミスとしてエラーにする）。

    戻り値: (pages, cell_meta)
      pages: 各ページの RGBA uint8 配列
      cell_meta: 入力順に対応する [{"id","page","x","y","w","h"}, ...]
    """
    if not cells:
        return [], []
    cell_w, cell_h = cell_wh
    n = len(cells)

    stride_w = cell_w + padding
    stride_h = cell_h + padding
    page_w = cols * stride_w - padding if cols > 0 else 0
    if page_w > max_page:
        raise ValueError(
            f"cols={cols} 列 x cell_w={cell_w} (+padding={padding}) の幅 {page_w} が "
            f"max_page={max_page} を超える。cols かセルサイズを減らすこと。"
        )
    max_rows_per_page = max(1, (max_page + padding) // stride_h)

    pages: list[np.ndarray] = []
    cell_meta: list[dict] = []

    idx = 0
    page_idx = 0
    while idx < n:
        remaining = n - idx
        rows_needed = -(-remaining // cols)  # ceil division
        rows_this_page = min(max_rows_per_page, rows_needed)
        page_h = rows_this_page * stride_h - padding
        page = np.zeros((page_h, page_w, 4), dtype=np.uint8)

        for r in range(rows_this_page):
            for c in range(cols):
                if idx >= n:
                    break
                img = cells[idx]
                ih, iw = img.shape[0], img.shape[1]
                if iw > cell_w or ih > cell_h:
                    raise ValueError(
                        f"cell[{idx}] size ({iw}x{ih}) exceeds cell_wh {cell_wh}; "
                        f"call scale_to_cell first"
                    )
                x = c * stride_w
                y = r * stride_h
                off_x = (cell_w - iw) // 2
                off_y = cell_h - ih  # 下辺中央アンカー
                px, py = x + off_x, y + off_y
                page[py:py + ih, px:px + iw] = img
                if extrude > 0:
                    _apply_extrude(page, px, py, iw, ih, extrude, page_w, page_h)
                cell_meta.append({
                    "id": f"c{idx}", "page": page_idx,
                    "x": int(x), "y": int(y), "w": int(cell_w), "h": int(cell_h),
                })
                idx += 1
        pages.append(page)
        page_idx += 1

    return pages, cell_meta


def _apply_extrude(page: np.ndarray, px: int, py: int, w: int, h: int,
                    extrude: int, page_w: int, page_h: int) -> None:
    """セル画像の外周ピクセルを extrude 分だけ複製して縁のにじみを防ぐ。ページ境界は越えない。"""
    x0, y0, x1, y1 = px, py, px + w, py + h
    left_col = page[y0:y1, x0:x0 + 1].copy()
    right_col = page[y0:y1, x1 - 1:x1].copy()
    for e in range(1, extrude + 1):
        if x0 - e >= 0:
            page[y0:y1, x0 - e:x0 - e + 1] = left_col
        if x1 - 1 + e < page_w:
            page[y0:y1, x1 - 1 + e:x1 + e] = right_col

    x0e, x1e = max(0, x0 - extrude), min(page_w, x1 + extrude)
    top_row = page[y0:y0 + 1, x0e:x1e].copy()
    bottom_row = page[y1 - 1:y1, x0e:x1e].copy()
    for e in range(1, extrude + 1):
        if y0 - e >= 0:
            page[y0 - e:y0 - e + 1, x0e:x1e] = top_row
        if y1 - 1 + e < page_h:
            page[y1 - 1 + e:y1 + e, x0e:x1e] = bottom_row
