/*
 * 編集モード(コマの移動・拡大縮小)。ステージの canvas 上に枠と四隅ハンドルを重ねる。
 *
 * - 本体ドラッグ=移動、角ドラッグ=画像中心基準の等比拡大縮小、ホイール=倍率、
 *   矢印キー=1px(Shift=10px。キー処理は index.html から nudge() を呼ぶ)
 * - step(±1) で編集したまま前後のコマへ移る。それまでの変更は st.base に積み、
 *   確定時にまとめて1回だけDBへ書く(Undo 1回で全部戻る)。キャンセルで全部捨てる。
 * - 下書きは CanvasView.setOverride() で描くだけ。
 * - 透明度(seeThrough %)は編集中の表示だけに使い、保存しない。上げると編集中のコマが
 *   透け、後ろに前のコマが見える(CanvasView.setOnion)。
 * - 適用範囲: one=このコマ / selected=選択中のコマ / layer=レイヤーの全コマ。
 *   移動は差分を足し、倍率は変更したときだけ同じ値を入れる。
 * - 丸めは floor(x+0.5)(CLAUDE.md 規則3)。
 */
const TransformEdit = (() => {
  "use strict";
  const MIN_S = 0.05, MAX_S = 8;
  let wrap = null;
  let overlay = null;
  let box = null;
  let cb = {};
  let st = null;   // {layerId, expId, base:[exposure], selectedIds, scope, seeThrough, orig, draft}
  let lastSeeThrough = 0;   // 次に編集を開いたときも同じ透明度から始める

  const fh = (x) => Math.floor(x + 0.5);
  const clampS = (s) => Math.min(MAX_S, Math.max(MIN_S, Math.floor(s * 100 + 0.5) / 100));

  function attach(stageWrapEl, callbacks) {
    wrap = stageWrapEl;
    cb = callbacks || {};
    overlay = document.createElement("div");
    overlay.className = "xf-overlay";
    overlay.hidden = true;
    box = document.createElement("div");
    box.className = "xf-box";
    ["nw", "ne", "sw", "se"].forEach((c) => {
      const h = document.createElement("div");
      h.className = "xf-handle " + c;
      h.addEventListener("mousedown", (ev) => startScale(ev));
      box.appendChild(h);
    });
    box.addEventListener("mousedown", (ev) => { if (ev.target === box) startMove(ev); });
    overlay.appendChild(box);
    wrap.appendChild(overlay);
    wrap.addEventListener("wheel", (ev) => {
      if (!st) return;
      ev.preventDefault();
      set({ scale: st.draft.scale * (ev.deltaY < 0 ? 1.05 : 1 / 1.05) });
    }, { passive: false });
    CanvasView.onAfterRender(refresh);
  }

  function layerOf() {
    const comp = cb.getComp && cb.getComp();
    return comp && st ? comp.layers.find((l) => l.id === st.layerId) : null;
  }

  function pickTarget(expId) {
    const e = st.base.find((x) => x.id === expId);
    st.expId = expId;
    st.orig = { dx: e.dx, dy: e.dy, scale: e.scale || 1 };
    st.draft = Object.assign({}, st.orig);
  }

  function start(layerId, expId, selectedIds) {
    const comp = cb.getComp();
    const ly = comp && comp.layers.find((l) => l.id === layerId);
    if (!ly || !ly.exposures.some((x) => x.id === expId)) return false;
    const sel = (selectedIds || []).filter((id) => ly.exposures.some((x) => x.id === id));
    st = { layerId: layerId, base: ly.exposures.map((e) => Object.assign({}, e)),
           selectedIds: sel.includes(expId) ? sel : [expId],
           scope: sel.length > 1 ? "selected" : "one", seeThrough: lastSeeThrough };
    pickTarget(expId);
    overlay.hidden = false;
    apply();
    return true;
  }

  function targets() {
    if (st.scope === "layer") return st.base.map((e) => e.id);
    if (st.scope === "selected") return st.selectedIds;
    return [st.expId];
  }

  /** st.base に今の下書きを適用した後のレイヤー全コマ。 */
  function nextExposures() {
    if (!st) return null;
    const ids = new Set(targets());
    const ddx = st.draft.dx - st.orig.dx, ddy = st.draft.dy - st.orig.dy;
    const scaleChanged = st.draft.scale !== st.orig.scale;
    return st.base.map((e) => {
      if (!ids.has(e.id)) return e;
      return Object.assign({}, e, {
        dx: e.dx + ddx, dy: e.dy + ddy,
        scale: scaleChanged ? st.draft.scale : (e.scale || 1),
      });
    });
  }

  function apply() {
    const next = nextExposures();
    if (!next) return;
    const map = new Map();
    next.forEach((e) => map.set(e.id, { dx: e.dx, dy: e.dy, scale: e.scale }));
    CanvasView.setOnion({ layerId: st.layerId, expId: st.expId, alpha: 1 - st.seeThrough / 100 });
    CanvasView.setOverride(map);   // 再描画 → refresh() でオーバーレイも追従
    cb.onChange && cb.onChange(get());
  }

  function set(patch) {
    if (!st) return;
    const d = st.draft;
    if (patch.dx !== undefined) d.dx = fh(patch.dx);
    if (patch.dy !== undefined) d.dy = fh(patch.dy);
    if (patch.scale !== undefined) d.scale = clampS(patch.scale);
    if (patch.scope !== undefined) st.scope = patch.scope;
    if (patch.seeThrough !== undefined) {
      st.seeThrough = Math.min(100, Math.max(0, fh(patch.seeThrough)));
      lastSeeThrough = st.seeThrough;
    }
    apply();
  }

  /** 編集を続けたまま前後のコマへ移る。ここまでの変更は保持する。 */
  function step(delta) {
    if (!st) return;
    st.base = nextExposures();
    const i = st.base.findIndex((e) => e.id === st.expId);
    const j = Math.min(st.base.length - 1, Math.max(0, i + delta));
    if (j === i) return;
    pickTarget(st.base[j].id);
    // 選択外のコマに移ったら、選択中コマへの一括適用はやめて「このコマだけ」にする
    if (st.scope === "selected" && !st.selectedIds.includes(st.expId)) st.scope = "one";
    cb.onStep && cb.onStep(st.layerId, st.expId);
    apply();
  }

  function nudge(x, y) { if (st) set({ dx: st.draft.dx + x, dy: st.draft.dy + y }); }

  function resetScale() { set({ scale: 1 }); }

  function center() {
    const comp = cb.getComp();
    const e = st && st.base.find((x) => x.id === st.expId);
    const size = e && e.image_url ? CanvasView.imageSize(e.image_url) : null;
    if (!size) return;
    set({ dx: (comp.canvas_w - size.w) / 2, dy: (comp.canvas_h - size.h) / 2 });
  }

  function refresh() {
    if (!st || !overlay) return;
    const comp = cb.getComp();
    const canvas = CanvasView.getCanvas();
    const r = comp && CanvasView.exposureRect(comp, st.layerId, st.expId);
    if (!r || !canvas.width) { box.hidden = true; return; }
    box.hidden = false;
    const k = canvas.clientWidth / canvas.width;
    const cr = canvas.getBoundingClientRect(), wr = wrap.getBoundingClientRect();
    box.style.left = (cr.left - wr.left + r.x * k) + "px";
    box.style.top = (cr.top - wr.top + r.y * k) + "px";
    box.style.width = Math.max(6, r.w * k) + "px";
    box.style.height = Math.max(6, r.h * k) + "px";
  }

  function canvasK() {
    const c = CanvasView.getCanvas();
    return c.clientWidth / c.width || 1;
  }

  function drag(ev, onMove) {
    ev.preventDefault();
    ev.stopPropagation();
    const sx = ev.clientX, sy = ev.clientY;
    const from = Object.assign({}, st.draft);
    function move(e) { onMove(e, sx, sy, from); }
    function up() {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    }
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  }

  function startMove(ev) {
    drag(ev, (e, sx, sy, from) => {
      const k = canvasK();
      set({ dx: from.dx + (e.clientX - sx) / k, dy: from.dy + (e.clientY - sy) / k });
    });
  }

  function startScale(ev) {
    const br = box.getBoundingClientRect();
    const cx = br.left + br.width / 2, cy = br.top + br.height / 2;
    const d0 = Math.max(4, Math.hypot(ev.clientX - cx, ev.clientY - cy));
    drag(ev, (e, sx, sy, from) => {
      const d = Math.hypot(e.clientX - cx, e.clientY - cy);
      set({ scale: from.scale * d / d0 });
    });
  }

  function finish() {
    st = null;
    overlay.hidden = true;
    CanvasView.setOnion(null);
    CanvasView.setOverride(null);
  }

  function commit() {
    if (!st) return;
    const layerId = st.layerId;
    const next = nextExposures();
    const ly = layerOf();
    const changed = !!ly && next.some((e, i) => {
      const o = ly.exposures[i];
      return !o || o.id !== e.id || o.dx !== e.dx || o.dy !== e.dy || (o.scale || 1) !== (e.scale || 1);
    });
    finish();
    if (changed && cb.onCommit) cb.onCommit(layerId, next);
    else if (cb.onCancel) cb.onCancel();
  }

  function cancel() {
    if (!st) return;
    finish();
    cb.onCancel && cb.onCancel();
  }

  function get() {
    if (!st) return null;
    return { layerId: st.layerId, expId: st.expId, scope: st.scope, seeThrough: st.seeThrough,
             selectedCount: st.selectedIds.length,
             pos: st.base.findIndex((e) => e.id === st.expId) + 1, count: st.base.length,
             draft: Object.assign({}, st.draft) };
  }

  return { attach: attach, start: start, set: set, step: step, nudge: nudge, center: center,
           resetScale: resetScale, commit: commit, cancel: cancel, refresh: refresh,
           isActive: () => !!st, get: get };
})();
