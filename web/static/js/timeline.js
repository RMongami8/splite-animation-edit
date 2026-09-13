/*
 * 下部タイムライン。レイヤーごとに1行、コマを hold_ticks に比例した幅で並べる。
 *
 * - 時間→px は線形固定(scale px/ms)。最小幅でクランプしないので、再生ヘッド位置と
 *   コマ位置が常に一致する(ズームで細かいコマを広げて操作する)。
 * - 通常時: クリックで選択(Ctrl=追加/解除、Shift=範囲)、ダブルクリック/右クリックで
 *   コマメニュー、ドラッグ&ドロップで同一レイヤー内の並べ替え。確定は呼び出し側が
 *   PUT /api/layers/{id}/exposures を1回叩く形にまとめる(§4の規則)。
 * - 削除モード: 選択コマに✕印を出す。押したままなぞると範囲選択、Ctrl+押下で切り替え。
 *   なぞっている間はDOMのクラスだけを更新し、離したときに onPaint で1回だけ通知する。
 * - ルーラーのドラッグ、およびコマの無い余白のクリックでシークする。
 * - 再生中は updatePlayhead() だけを呼び、DOMは作り直さない。
 */
const Timeline = (() => {
  "use strict";
  const LABEL_W = 104;          // ラベル列の幅(px)。ルーラーと各行で揃える
  let container = null;
  let cb = {};
  let scale = 0.4;              // px / ms
  let inner = null;
  let playhead = null;
  let lastComp = null;
  let lastSel = null;
  let paint = null;             // 削除モードのなぞり選択中の状態

  function attach(el, callbacks) {
    container = el;
    cb = callbacks || {};
    window.addEventListener("mouseup", endPaint);
  }

  function getScale() { return scale; }

  function setScale(next) {
    scale = Math.min(4, Math.max(0.05, next));
    if (lastComp) render(lastComp, lastSel);
  }

  /**
   * sel = {layerId, ids: Set, primaryId, deleteMode}
   */
  function render(comp, sel) {
    if (!container || !comp) return;
    lastComp = comp;
    lastSel = sel || { layerId: null, ids: new Set(), primaryId: null, deleteMode: false };
    const scrollLeft = container.scrollLeft;
    container.innerHTML = "";

    inner = document.createElement("div");
    inner.className = "tl-inner";
    const contentW = Math.max(240, Math.ceil(comp.total_ticks * scale) + 80);
    inner.style.minWidth = (LABEL_W + contentW) + "px";

    inner.appendChild(buildRuler(comp, contentW));

    const layers = comp.layers.slice().sort((a, b) => a.z - b.z);
    if (!layers.length) {
      const empty = document.createElement("div");
      empty.className = "tl-empty";
      empty.textContent = "レイヤーがありません。左の Layers パネルの ＋ から追加してください。";
      inner.appendChild(empty);
    }
    for (const ly of layers) {
      inner.appendChild(buildRow(ly, contentW));
    }

    playhead = document.createElement("div");
    playhead.className = "tl-playhead";
    playhead.style.left = LABEL_W + "px";
    inner.appendChild(playhead);

    container.appendChild(inner);
    container.scrollLeft = scrollLeft;
  }

  function buildRuler(comp, contentW) {
    const row = document.createElement("div");
    row.className = "tl-ruler-row";

    const gutter = document.createElement("div");
    gutter.className = "tl-gutter";
    const total = document.createElement("span");
    total.className = "mono";
    total.textContent = comp.total_ticks + " ms";
    gutter.appendChild(total);
    row.appendChild(gutter);

    const ruler = document.createElement("div");
    ruler.className = "tl-ruler";
    ruler.style.width = contentW + "px";
    const stepMs = pickRulerStep();
    for (let t = 0; t <= comp.total_ticks + stepMs; t += stepMs) {
      const tick = document.createElement("div");
      tick.className = "tl-tick";
      tick.style.left = (t * scale) + "px";
      const label = document.createElement("span");
      label.className = "mono";
      label.textContent = t >= 1000 ? (t / 1000) + "s" : t + "";
      tick.appendChild(label);
      ruler.appendChild(tick);
    }
    attachSeek(ruler);
    row.appendChild(ruler);
    return row;
  }

  function pickRulerStep() {
    // 目盛りが詰まりすぎない間隔(px換算で60px以上)を選ぶ
    const candidates = [50, 100, 250, 500, 1000, 2000, 5000];
    for (const ms of candidates) {
      if (ms * scale >= 60) return ms;
    }
    return 10000;
  }

  function attachSeek(el) {
    function seekFromEvent(ev) {
      const rect = el.getBoundingClientRect();
      const x = Math.max(0, ev.clientX - rect.left);
      cb.onSeek && cb.onSeek(x / scale);
    }
    el.addEventListener("mousedown", (ev) => {
      ev.preventDefault();
      seekFromEvent(ev);
      function move(e) { seekFromEvent(e); }
      function up() {
        window.removeEventListener("mousemove", move);
        window.removeEventListener("mouseup", up);
      }
      window.addEventListener("mousemove", move);
      window.addEventListener("mouseup", up);
    });
  }

  function buildRow(ly, contentW) {
    const row = document.createElement("div");
    row.className = "tl-row";
    const inLayer = lastSel.layerId === ly.id;
    const delMode = lastSel.deleteMode && inLayer;

    const label = document.createElement("div");
    label.className = "tl-label";
    const name = document.createElement("span");
    name.className = "tl-label-name";
    name.textContent = ly.name;
    label.appendChild(name);
    const meta = document.createElement("span");
    meta.className = "tl-label-meta mono";
    meta.textContent = ly.exposures.length + "コマ";
    label.appendChild(meta);
    if (ly.blend === "add") {
      const badge = document.createElement("span");
      badge.className = "badge add";
      badge.textContent = "add";
      label.appendChild(badge);
    }
    if (!ly.visible) label.classList.add("is-hidden");
    row.appendChild(label);

    const track = document.createElement("div");
    track.className = "tl-track";
    track.style.width = contentW + "px";

    const cells = document.createElement("div");
    cells.className = "tl-cells";
    cells.style.marginLeft = (ly.start_ticks * scale) + "px";

    const cellEls = [];
    ly.exposures.forEach((e, idx) => {
      const cell = document.createElement("div");
      const isSel = inLayer && lastSel.ids.has(e.id);
      cell.className = "tl-cell"
        + (isSel ? " selected" : "")
        + (inLayer && e.id === lastSel.primaryId ? " primary" : "")
        + (delMode ? " del-mode" : "");
      cell.dataset.expId = e.id;
      cell.style.width = Math.max(3, e.hold_ticks * scale) + "px";
      cell.draggable = !lastSel.deleteMode;
      const sc = e.scale && e.scale !== 1 ? `  ×${e.scale}` : "";
      cell.title = `#${idx + 1}  ${e.hold_ticks}ms  dx=${e.dx} dy=${e.dy}${sc}\nダブルクリック/右クリックでメニュー`;

      if (e.image_url) {
        const thumb = document.createElement("img");
        thumb.src = e.image_url;
        thumb.alt = "";
        thumb.draggable = false;
        cell.appendChild(thumb);
      }
      // 幅の狭いコマに数字を出すと重なって読めないので、入る幅があるときだけ出す
      // (124コマのような素材では既定ズームで1コマ17px程度になる)
      if (e.hold_ticks * scale >= 34) {
        const dur = document.createElement("span");
        dur.className = "tl-dur mono";
        dur.textContent = e.hold_ticks;
        cell.appendChild(dur);
      }
      const mark = document.createElement("span");
      mark.className = "tl-delmark";
      mark.textContent = "✕";
      cell.appendChild(mark);
      cellEls.push(cell);

      if (lastSel.deleteMode) {
        cell.addEventListener("mousedown", (ev) => {
          if (ev.button !== 0) return;
          ev.preventDefault();
          ev.stopPropagation();
          startPaint(ly, idx, ev.ctrlKey || ev.metaKey, cellEls);
        });
        cell.addEventListener("mouseenter", () => { if (paint && paint.layerId === ly.id) extendPaint(idx); });
        cell.addEventListener("contextmenu", (ev) => ev.preventDefault());
      } else {
        // 1回目のクリックで選択→再描画でDOMが作り直されるため dblclick は当てにできない。
        // click の detail(連続クリック回数)で2回目を判定してメニューを開く。
        cell.addEventListener("click", (ev) => {
          ev.stopPropagation();
          if (ev.detail >= 2) {
            cb.onCellMenu && cb.onCellMenu(ly.id, e.id, ev.clientX, ev.clientY);
            return;
          }
          cb.onSelect && cb.onSelect(ly.id, e.id, {
            ctrl: ev.ctrlKey || ev.metaKey, shift: ev.shiftKey });
        });
        cell.addEventListener("contextmenu", (ev) => {
          ev.preventDefault();
          cb.onCellMenu && cb.onCellMenu(ly.id, e.id, ev.clientX, ev.clientY);
        });
        cell.addEventListener("dragstart", (ev) => {
          ev.dataTransfer.setData("text/plain", JSON.stringify({ layerId: ly.id, idx: idx }));
          cell.classList.add("dragging");
        });
        cell.addEventListener("dragend", () => cell.classList.remove("dragging"));
        cell.addEventListener("dragover", (ev) => {
          ev.preventDefault();
          cell.classList.add("drop-target");
        });
        cell.addEventListener("dragleave", () => cell.classList.remove("drop-target"));
        cell.addEventListener("drop", (ev) => {
          ev.preventDefault();
          cell.classList.remove("drop-target");
          let src;
          try { src = JSON.parse(ev.dataTransfer.getData("text/plain")); } catch (err) { return; }
          if (!src || src.layerId !== ly.id) return;   // レイヤー間移動は範囲外
          if (src.idx === idx) return;
          cb.onReorder && cb.onReorder(ly.id, src.idx, idx);
        });
      }
      cells.appendChild(cell);
    });

    track.appendChild(cells);
    // コマの無い余白のクリックでシーク
    track.addEventListener("mousedown", (ev) => {
      if (ev.target !== track && ev.target !== cells) return;
      const rect = track.getBoundingClientRect();
      cb.onSeek && cb.onSeek(Math.max(0, ev.clientX - rect.left) / scale);
    });
    row.appendChild(track);
    return row;
  }

  // ---- 削除モードのなぞり選択 ----

  function startPaint(ly, idx, ctrl, cellEls) {
    const inLayer = lastSel.layerId === ly.id;
    const base = new Set(inLayer && ctrl ? lastSel.ids : []);
    const id = ly.exposures[idx].id;
    // Ctrl+押下はそのコマの切り替えから始める。通常の押下は押したコマから選び直す。
    let adding = true;
    if (ctrl && base.has(id)) { base.delete(id); adding = false; }
    paint = { layerId: ly.id, exposures: ly.exposures, startIdx: idx, base: base,
              adding: adding, cellEls: cellEls, current: new Set(base) };
    extendPaint(idx);
  }

  function extendPaint(idx) {
    const a = Math.min(paint.startIdx, idx), b = Math.max(paint.startIdx, idx);
    const next = new Set(paint.base);
    for (let i = a; i <= b; i++) {
      const id = paint.exposures[i].id;
      if (paint.adding) next.add(id); else next.delete(id);
    }
    paint.current = next;
    paint.cellEls.forEach((el) => el.classList.toggle("selected", next.has(el.dataset.expId)));
  }

  function endPaint() {
    if (!paint) return;
    const p = paint;
    paint = null;
    const ordered = p.exposures.filter((e) => p.current.has(e.id)).map((e) => e.id);
    cb.onPaint && cb.onPaint(p.layerId, ordered, p.exposures[p.startIdx].id);
  }

  function updatePlayhead(tTicks) {
    if (!playhead) return;
    playhead.style.left = (LABEL_W + tTicks * scale) + "px";
  }

  return { attach: attach, render: render, updatePlayhead: updatePlayhead,
           getScale: getScale, setScale: setScale };
})();
