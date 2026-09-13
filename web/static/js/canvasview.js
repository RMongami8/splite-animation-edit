/*
 * 中央の合成プレビュー。core/timeline.py の layer_frame_at と core/composite.py の
 * blend 式に相当する処理を Canvas 2D の描画オプション(globalCompositeOperation /
 * globalAlpha)で近似する。プレビュー用の簡易実装であり、§6 の画素一致検証対象では
 * ない(数値検証は tools/selftest_parity.py が Python/Node 間で行う)。
 *
 * キャンバスは Composition の実ピクセル寸法で描き、表示サイズだけを親要素に
 * 収まるよう縮小する(画面外にはみ出さないための必須要件)。背景(市松/単色)は
 * CSS 側が受け持ち、ここでは透明のまま描く。
 *
 * 倍率(exposure.scale)は画像中心基準。dx/dy は倍率1のときの左上位置。
 * 編集モード中は setOverride() の下書き値で描き、setOnion({layerId, expId, alpha}) で
 * 編集中のコマを alpha で透かし、その後ろに前のコマを描く(表示のみ。保存しない)。
 */
const CanvasView = (() => {
  "use strict";
  let canvas = null;
  let ctx = null;
  let container = null;
  const imageCache = new Map();
  let lastComp = null;
  let lastT = 0;
  let fittedFor = "";
  let override = null;     // Map(expId -> {dx, dy, scale})
  let onion = null;        // {layerId, expId, alpha}
  const afterRender = [];

  function attach(canvasEl, containerEl) {
    canvas = canvasEl;
    ctx = canvas.getContext("2d");
    container = containerEl || null;
    if (container && typeof ResizeObserver !== "undefined") {
      // レイアウトが落ち着いた次フレームで測る。リサイズ途中のサイズで
      // 計算すると、キャンバスが小さいまま取り残される。
      new ResizeObserver(() => requestAnimationFrame(() => { fit(); emitAfterRender(); })).observe(container);
    }
  }

  function loadImage(url) {
    let img = imageCache.get(url);
    if (!img) {
      img = new Image();
      // 読み込み完了は非同期なので、初回描画時にまだ未読込のフレームがあっても
      // ロード完了後に自動で再描画する(でないと停止中は何も出ないままになる)。
      img.addEventListener("load", () => { if (lastComp) render(lastComp, lastT); });
      img.src = url;
      imageCache.set(url, img);
    }
    return img;
  }

  function buildSpans(layer) {
    let acc = layer.start_ticks;
    return layer.exposures.map((e) => {
      const s = acc, en = acc + e.hold_ticks;
      acc = en;
      return { s: s, en: en, e: e };
    });
  }

  function exposureAt(spans, t, afterEnd) {
    if (!spans.length) return null;
    const start0 = spans[0].s, endLast = spans[spans.length - 1].en;
    if (t < start0) return null;
    if (t >= endLast) {
      if (afterEnd === "hide") return null;
      if (afterEnd === "hold") return spans[spans.length - 1].e;
      if (afterEnd === "loop") {
        const loopLen = endLast - start0;
        if (loopLen <= 0) return spans[spans.length - 1].e;
        const rel = start0 + (((t - start0) % loopLen) + loopLen) % loopLen;
        return findSpan(spans, rel);
      }
    }
    return findSpan(spans, t);
  }

  function findSpan(spans, t) {
    for (let i = 0; i < spans.length; i++) {
      if (t >= spans[i].s && t < spans[i].en) return spans[i].e;
    }
    return spans[spans.length - 1].e;
  }

  /** Composition の実寸を保ったまま、表示サイズだけ親要素に収める。 */
  function fit() {
    if (!canvas || !lastComp || !container) return;
    const cw = container.clientWidth, ch = container.clientHeight;
    // 同じ条件なら何もしない(render から毎フレーム呼んでも無駄な再計算をしない)
    const key = cw + "x" + ch + "x" + lastComp.canvas_w + "x" + lastComp.canvas_h;
    if (key === fittedFor) return;
    // 余白は最小限にし、小さいキャンバスは大きく引き伸ばしてステージを埋める
    // (中央の余白が広すぎるという指摘への対応)
    const pad = 28;
    const availW = Math.max(48, cw - pad);
    const availH = Math.max(48, ch - pad);
    const scale = Math.min(availW / lastComp.canvas_w, availH / lastComp.canvas_h, 8);
    canvas.style.width = Math.max(24, Math.floor(lastComp.canvas_w * scale)) + "px";
    canvas.style.height = Math.max(24, Math.floor(lastComp.canvas_h * scale)) + "px";
    fittedFor = key;
  }

  /** 下書き値を反映した exposure(編集モード中のみ差し替わる)。 */
  function effective(e) {
    if (!override || !override.has(e.id)) return e;
    return Object.assign({}, e, override.get(e.id));
  }

  /** 画像を置く矩形(キャンバス実ピクセル)。倍率は画像中心基準。 */
  function placement(e, img) {
    const s = e.scale || 1;
    const nw = img.naturalWidth, nh = img.naturalHeight;
    const w = nw * s, h = nh * s;
    return { x: e.dx + (nw - w) / 2, y: e.dy + (nh - h) / 2, w: w, h: h };
  }

  function drawExposure(e, alpha, blend) {
    if (!e || !e.image_url) return;
    const img = loadImage(e.image_url);
    if (!img.complete || img.naturalWidth === 0) return;
    const r = placement(e, img);
    ctx.save();
    ctx.globalCompositeOperation = blend === "add" ? "lighter" : "source-over";
    ctx.globalAlpha = alpha;
    if (e.flip_x) {
      ctx.translate(r.x + r.w, r.y);
      ctx.scale(-1, 1);
      ctx.drawImage(img, 0, 0, r.w, r.h);
    } else {
      ctx.drawImage(img, r.x, r.y, r.w, r.h);
    }
    ctx.restore();
  }

  function render(comp, t) {
    if (!ctx || !comp) return;
    lastComp = comp;
    lastT = t;
    if (canvas.width !== comp.canvas_w) canvas.width = comp.canvas_w;
    if (canvas.height !== comp.canvas_h) canvas.height = comp.canvas_h;
    // 毎回呼ぶ。中で条件が同じならすぐ返るので安い。これが無いと、リサイズ時に
    // ResizeObserver が取りこぼした分だけキャンバスが小さいまま残る。
    fit();

    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.globalCompositeOperation = "source-over";
    ctx.globalAlpha = 1;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const layers = comp.layers.slice().sort((a, b) => a.z - b.z);
    for (const ly of layers) {
      if (!ly.visible) continue;
      const onionHere = onion && onion.layerId === ly.id;
      if (onionHere && onion.alpha < 1) {
        // 編集中のコマを透かしたとき、後ろに見えるのは「前のコマ」(ループなら先頭の前は末尾)
        const i = ly.exposures.findIndex((x) => x.id === onion.expId);
        let j = i - 1;
        if (j < 0 && ly.after_end === "loop") j = ly.exposures.length - 1;
        if (i >= 0 && j >= 0 && j !== i) drawExposure(effective(ly.exposures[j]), ly.opacity, ly.blend);
      }
      const e = exposureAt(buildSpans(ly), t, ly.after_end);
      const alpha = onionHere && e && e.id === onion.expId ? onion.alpha : 1;
      if (e) drawExposure(effective(e), ly.opacity * alpha, ly.blend);
    }
    emitAfterRender();
  }

  function emitAfterRender() { afterRender.forEach((fn) => fn()); }

  /** 編集オーバーレイ用: 指定コマの矩形(キャンバス実ピクセル)。画像未読込なら null。 */
  function exposureRect(comp, layerId, expId) {
    const ly = comp && comp.layers.find((l) => l.id === layerId);
    const e = ly && ly.exposures.find((x) => x.id === expId);
    if (!e || !e.image_url) return null;
    const img = loadImage(e.image_url);
    if (!img.complete || img.naturalWidth === 0) return null;
    return placement(effective(e), img);
  }

  function imageSize(url) {
    const img = loadImage(url);
    return img.complete && img.naturalWidth ? { w: img.naturalWidth, h: img.naturalHeight } : null;
  }

  function setOverride(map) { override = map; if (lastComp) render(lastComp, lastT); }
  function setOnion(o) { onion = o; if (lastComp) render(lastComp, lastT); }
  function onAfterRender(fn) { afterRender.push(fn); }
  function getCanvas() { return canvas; }

  return { attach: attach, render: render, fit: fit,
           buildSpans: buildSpans, exposureAt: exposureAt,
           exposureRect: exposureRect, imageSize: imageSize,
           setOverride: setOverride, setOnion: setOnion,
           onAfterRender: onAfterRender, getCanvas: getCanvas };
})();
