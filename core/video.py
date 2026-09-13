"""動画I/O（プラン §11 の tools/doctor.py 判定・core/video.py 契約準拠）。

デコードは PyAV を第一経路にする。import av が失敗する環境でのみ ffmpeg
フォールバックを使う。フォールバック経路は ffprobe が同梱されない制約上、
正確な有理数 timebase が取得できず、showinfo の pts_time(秒, 浮動小数) を
ミリ秒に丸めた近似timebase(tb_num=1, tb_den=1000)を使う（実測PTSほど正確では
ない劣化措置であることを明示する）。どちらを使ったかは tools/doctor.py の
結果(docs/versions.md)で分かる。

抽出に -vsync 0 は使わない（非推奨）。ffmpeg 経路では -fps_mode passthrough を使う。
"""
import re
import secrets
import shutil
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

from core.composite import blend_normal
from core.imageio_ import probe_size, save_png

_ALPHA_PIX_FMT_TAGS = ("yuva", "rgba", "bgra", "argb", "abgr", "gbrap")


def _has_pyav() -> bool:
    try:
        import av  # noqa: F401
        return True
    except Exception:
        return False


def probe(path: Path) -> dict:
    """動画のメタデータと実測PTS列を取得する。

    戻り値: {"width","height","n_frames","tb_num","tb_den","rotation","codec",
             "pts_list":[int,...],"last_frame_dur_pts":int,"start_pts":int}
    """
    if _has_pyav():
        return _probe_pyav(Path(path))
    return _probe_ffmpeg(Path(path))


def extract_frames(path: Path, out_dir: Path) -> list[dict]:
    """動画をPNG連番として抽出する（絶対パスのまま保存。data root 相対化は呼び出し側）。

    戻り値: [{"frame_id","idx","pts","rel_path","width","height"}]
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if _has_pyav():
        return _extract_pyav(Path(path), out_dir)
    return _extract_ffmpeg(Path(path), out_dir)


# ---------------------------------------------------------------------------
# PyAV 経路（第一経路）
# ---------------------------------------------------------------------------

def _get_rotation(stream) -> int:
    try:
        rotate = stream.metadata.get("rotate")
        if rotate is not None:
            return int(rotate) % 360
    except Exception:
        pass
    return 0


def _detect_alpha(stream) -> bool:
    try:
        fmt_name = stream.codec_context.format.name
    except Exception:
        return False
    return any(tag in fmt_name for tag in _ALPHA_PIX_FMT_TAGS)


def _probe_pyav(path: Path) -> dict:
    import av
    container = av.open(str(path))
    try:
        stream = container.streams.video[0]
        tb = stream.time_base
        width = stream.codec_context.width
        height = stream.codec_context.height
        codec = stream.codec_context.name
        rotation = _get_rotation(stream)
        pts_list = []
        for frame in container.decode(stream):
            if frame.pts is not None:
                pts_list.append(int(frame.pts))
    finally:
        container.close()

    n_frames = len(pts_list)
    last_frame_dur_pts = _estimate_last_frame_dur(pts_list)
    start_pts = pts_list[0] if pts_list else 0

    return {
        "width": width, "height": height, "n_frames": n_frames,
        "tb_num": tb.numerator, "tb_den": tb.denominator,
        "rotation": rotation, "codec": codec,
        "pts_list": pts_list, "last_frame_dur_pts": last_frame_dur_pts,
        "start_pts": start_pts,
    }


def _extract_pyav(path: Path, out_dir: Path) -> list[dict]:
    import av
    container = av.open(str(path))
    results = []
    try:
        stream = container.streams.video[0]
        idx = 0
        for frame in container.decode(stream):
            if frame.pts is None:
                continue
            img = frame.to_ndarray(format="rgba")  # (H,W,4) uint8 ストレートアルファ
            frame_id = f"f{idx:04d}"
            dest = out_dir / f"{frame_id}.png"
            save_png(dest, img)
            results.append({
                "frame_id": frame_id, "idx": idx, "pts": int(frame.pts),
                "rel_path": str(dest),
                "width": int(img.shape[1]), "height": int(img.shape[0]),
            })
            idx += 1
    finally:
        container.close()
    return results


def _estimate_last_frame_dur(pts_list: list[int]) -> int:
    n = len(pts_list)
    if n < 2:
        return 0
    diffs = sorted(pts_list[i + 1] - pts_list[i] for i in range(n - 1))
    return diffs[len(diffs) // 2]  # 中央値: 外れ値(最初/最後のGOP境界等)に強い


# ---------------------------------------------------------------------------
# ffmpeg フォールバック経路（PyAV が使えない場合のみ）
# ---------------------------------------------------------------------------

def _ffmpeg_exe() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _probe_ffmpeg(path: Path) -> dict:
    exe = _ffmpeg_exe()
    result = subprocess.run(
        [exe, "-i", str(path), "-vf", "showinfo", "-f", "null", "-"],
        capture_output=True, text=True, timeout=120,
    )
    stderr = result.stderr

    m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", stderr)
    width, height = (int(m.group(1)), int(m.group(2))) if m else (0, 0)

    pts_times = [float(x) for x in re.findall(r"pts_time:([\d.]+)", stderr)]
    pts_list = [int(t * 1000 + 0.5) for t in pts_times]  # floor(x+0.5)丸め
    last_frame_dur_pts = _estimate_last_frame_dur(pts_list)
    start_pts = pts_list[0] if pts_list else 0

    return {
        "width": width, "height": height, "n_frames": len(pts_list),
        "tb_num": 1, "tb_den": 1000,  # 近似(ミリ秒)。PyAV経路のような実測有理数ではない
        "rotation": 0, "codec": "unknown",
        "pts_list": pts_list, "last_frame_dur_pts": last_frame_dur_pts,
        "start_pts": start_pts,
    }


def _extract_ffmpeg(path: Path, out_dir: Path) -> list[dict]:
    exe = _ffmpeg_exe()
    pattern = str(out_dir / "f%04d.png")
    result = subprocess.run(
        [exe, "-hide_banner", "-nostdin", "-y", "-i", str(path),
         "-fps_mode", "passthrough", pattern],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg extract failed: {result.stderr[-2000:]}")

    probed = _probe_ffmpeg(path)
    pts_list = probed["pts_list"]
    results = []
    for i, p in enumerate(sorted(out_dir.glob("f*.png"))):
        w, h = probe_size(p)
        results.append({
            "frame_id": f"f{i:04d}", "idx": i,
            "pts": pts_list[i] if i < len(pts_list) else i,
            "rel_path": str(p), "width": w, "height": h,
        })
    return results


# ---------------------------------------------------------------------------
# エンコード（GIF/MP4 の実際の書き出し利用は M2 の export パイプラインから）
# ---------------------------------------------------------------------------

def _composite_over_solid(rgba: np.ndarray, bg_rgb: tuple[int, int, int]) -> np.ndarray:
    """RGBA を不透明な単色背景に合成して RGB (H,W,3) を返す。
    core/composite.py の blend_normal と同じ式を使う（§6 の式を使い回す）。
    """
    h, w = rgba.shape[:2]
    bg = np.empty((h, w, 4), np.uint8)
    bg[..., 0], bg[..., 1], bg[..., 2] = bg_rgb[0], bg_rgb[1], bg_rgb[2]
    bg[..., 3] = 255
    out = blend_normal(bg, rgba, 1.0)
    return out[..., :3]


def encode_mp4(png_dir: Path, out: Path, fps: int, bg_rgb: tuple[int, int, int]) -> None:
    """png_dir 内の連番PNG(RGBA)を bg_rgb 背景で合成してからMP4にエンコードする。"""
    from core.imageio_ import load_rgba

    png_dir = Path(png_dir)
    pngs = sorted(png_dir.glob("*.png"))
    if not pngs:
        raise ValueError(f"no PNG frames found in {png_dir}")

    work_dir = Path(out).parent / f"_mp4_work_{secrets.token_hex(4)}"
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        for i, p in enumerate(pngs):
            rgba = load_rgba(p)
            flat = _composite_over_solid(rgba, bg_rgb)
            Image.fromarray(flat, mode="RGB").save(work_dir / f"{i:05d}.png")

        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        exe = _ffmpeg_exe()
        cmd = [exe, "-hide_banner", "-nostdin", "-y",
               "-framerate", str(fps), "-i", str(work_dir / "%05d.png"),
               "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
               "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
               "-movflags", "+faststart", str(out)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg mp4 encode failed: {result.stderr[-2000:]}")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def encode_gif(frames: list[tuple[Path, int]], out: Path,
                bg_rgb: tuple[int, int, int]) -> dict:
    """frames=[(png_path, dur_ms), ...] を bg_rgb 背景で合成してPillowでGIFを書く。

    GIFのdurationは10ms単位に量子化される。量子化前後の合計時間差を report で返す
    （出力前チェックに使う）。
    """
    from core.imageio_ import load_rgba

    images: list[Image.Image] = []
    durations: list[int] = []
    original_total = 0
    quantized_total = 0
    for p, dur_ms in frames:
        rgba = load_rgba(p)
        flat = _composite_over_solid(rgba, bg_rgb)
        images.append(Image.fromarray(flat, mode="RGB"))
        q = max(10, int(dur_ms / 10 + 0.5) * 10)  # floor(x+0.5)丸めで10ms単位に量子化
        durations.append(q)
        original_total += dur_ms
        quantized_total += q

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(
        out, format="GIF", save_all=True, append_images=images[1:],
        duration=durations, loop=0, disposal=2,
    )
    return {
        "original_total_ms": original_total,
        "quantized_total_ms": quantized_total,
        "diff_ms": quantized_total - original_total,
        "n_frames": len(images),
    }
