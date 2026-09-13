"""合成式（プラン §6 準拠）。JS 側 web/static/js/composite.js と1対1対応させる。

規則:
- すべて uint8、ストレートアルファ（非プリマルチプライ）。
- 中間計算は float32、最終だけ整数化。np.round は使わない。floor(x+0.5) で丸める。
- normal と add(glow) のみ実装する（smoke は matte 後に normal と同じ式を使う）。
"""
import numpy as np

_LUMA_R, _LUMA_G, _LUMA_B = 299, 587, 114


def _floor_half(x: np.ndarray) -> np.ndarray:
    return np.floor(x + 0.5)


def blend_normal(dst: np.ndarray, src: np.ndarray, opacity: float) -> np.ndarray:
    """dst, src: uint8 (H,W,4) ストレートRGBA。opacity: 0.0-1.0。戻り値: uint8 (H,W,4)。

    out_rgb = floor(src_rgb*a*op + dst_rgb*(1-a*op) + 0.5)
    out_a   = floor((a*op + (dst_a/255)*(1-a*op)) * 255 + 0.5)
    """
    dst_f = dst.astype(np.float32)
    src_f = src.astype(np.float32)
    a = src_f[..., 3:4] / 255.0
    op = np.float32(opacity)
    a_op = a * op

    out_rgb = _floor_half(src_f[..., :3] * a_op + dst_f[..., :3] * (1.0 - a_op))
    dst_a_norm = dst_f[..., 3:4] / 255.0
    out_a = _floor_half((a_op + dst_a_norm * (1.0 - a_op)) * 255.0)

    out = np.concatenate([out_rgb, out_a], axis=-1)
    return np.clip(out, 0, 255).astype(np.uint8)


def blend_add(dst: np.ndarray, src: np.ndarray, opacity: float) -> np.ndarray:
    """発光素材の加算合成。src の RGB を発光量として dst に加算する。

    out_rgb = clamp(dst_rgb + floor(src_rgb*op + 0.5), 0, 255)
    out_a   = max(dst_a, floor(luma*op + 0.5))
    luma    = floor((299*R + 587*G + 114*B) / 1000 + 0.5)  (src の RGB から算出)
    """
    dst_f = dst.astype(np.float32)
    src_f = src.astype(np.float32)
    op = np.float32(opacity)

    add_rgb = _floor_half(src_f[..., :3] * op)
    out_rgb = np.clip(dst_f[..., :3] + add_rgb, 0, 255)

    luma = _floor_half(
        (_LUMA_R * src_f[..., 0] + _LUMA_G * src_f[..., 1] + _LUMA_B * src_f[..., 2]) / 1000.0
    )
    out_a = np.maximum(dst_f[..., 3], _floor_half(luma * op))

    out = np.concatenate([out_rgb, out_a[..., None]], axis=-1)
    return np.clip(out, 0, 255).astype(np.uint8)


def compose_at(comp: dict, layer_images: list[dict], bg_rgba: tuple[int, int, int, int]
               ) -> np.ndarray:
    """1時刻分の合成結果を作る。

    comp: {"canvas_w", "canvas_h"}
    layer_images: z順（下から上）に並んだ [{"rgba": np.ndarray(H,W,4) or None,
                  "blend": "normal"|"add", "opacity": float, "dx": int, "dy": int}]
                  「その時刻に表示するものが無い」レイヤーは rgba=None を渡す。
    bg_rgba: (R,G,B,A) の背景色。

    戻り値: uint8 (canvas_h, canvas_w, 4)
    """
    w, h = comp["canvas_w"], comp["canvas_h"]
    canvas = np.empty((h, w, 4), dtype=np.uint8)
    canvas[..., 0] = bg_rgba[0]
    canvas[..., 1] = bg_rgba[1]
    canvas[..., 2] = bg_rgba[2]
    canvas[..., 3] = bg_rgba[3]

    for layer in layer_images:
        rgba = layer.get("rgba")
        if rgba is None:
            continue
        dx, dy = layer.get("dx", 0), layer.get("dy", 0)
        placed = _place_on_canvas(rgba, w, h, dx, dy)
        blend = layer.get("blend", "normal")
        opacity = layer.get("opacity", 1.0)
        if blend == "add":
            canvas = blend_add(canvas, placed, opacity)
        else:
            canvas = blend_normal(canvas, placed, opacity)
    return canvas


def _place_on_canvas(rgba: np.ndarray, canvas_w: int, canvas_h: int,
                      dx: int, dy: int) -> np.ndarray:
    """rgba (h,w,4) を (dx,dy) だけずらしてキャンバスサイズに配置する。
    キャンバス外にはみ出す部分はクリップし、覆われない部分は透明(0,0,0,0)にする。
    """
    out = np.zeros((canvas_h, canvas_w, 4), dtype=np.uint8)
    src_h, src_w = rgba.shape[:2]

    dst_x0, dst_y0 = dx, dy
    dst_x1, dst_y1 = dx + src_w, dy + src_h

    src_x0 = max(0, -dst_x0)
    src_y0 = max(0, -dst_y0)
    dst_x0c = max(0, dst_x0)
    dst_y0c = max(0, dst_y0)
    dst_x1c = min(canvas_w, dst_x1)
    dst_y1c = min(canvas_h, dst_y1)

    if dst_x1c <= dst_x0c or dst_y1c <= dst_y0c:
        return out

    src_x1 = src_x0 + (dst_x1c - dst_x0c)
    src_y1 = src_y0 + (dst_y1c - dst_y0c)

    out[dst_y0c:dst_y1c, dst_x0c:dst_x1c] = rgba[src_y0:src_y1, src_x0:src_x1]
    return out
