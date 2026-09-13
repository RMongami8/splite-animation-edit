/*
 * 右パネル: 選択中レイヤー / Exposure のプロパティ編集。
 * 編集は呼び出し側の History 経由コマンドに渡す(Undo/Redo対象)。
 * 画像差し替えのみ一方向操作でUndo対象外(history.js のコメント参照)。
 */
const Inspector = (() => {
  "use strict";
  const fh = (x) => Math.floor(x + 0.5);   // CLAUDE.md 規則3
  let container = null;
  let cb = {};
  let info = {};

  function attach(el, callbacks) {
    container = el;
    cb = callbacks || {};
  }

  function render(layer, exposure, selInfo) {
    info = selInfo || {};
    if (!container) return;
    container.innerHTML = "";

    if (!layer) {
      container.appendChild(emptyState(
        "レイヤーを選択すると、ここで不透明度・合成方法・コマの表示時間を調整できます。"
      ));
      return;
    }

    container.appendChild(layerBlock(layer));
    if (info.count > 1 && !exposure) {
      container.appendChild(emptyState(info.count + "コマ選択中です。"));
    } else if (exposure) {
      container.appendChild(exposureBlock(exposure));
    } else {
      container.appendChild(emptyState("下のタイムラインでコマをクリックすると、そのコマの設定が出ます。"));
    }
  }

  function emptyState(text) {
    const div = document.createElement("div");
    div.className = "insp-empty";
    div.textContent = text;
    return div;
  }

  function layerBlock(layer) {
    const block = document.createElement("section");
    block.className = "insp-block";

    const head = document.createElement("div");
    head.className = "insp-head";
    const h4 = document.createElement("h4");
    h4.textContent = "レイヤー — " + layer.name;
    head.appendChild(h4);
    const del = iconButton("レイヤーを削除",
      '<path d="M4 6h12M8 6V4h4v2M6 6l1 10h6l1-10"/>');
    del.classList.add("danger");
    del.addEventListener("click", () => {
      if (cb.onDeleteLayer) cb.onDeleteLayer(layer.id, layer.name);
    });
    head.appendChild(del);
    block.appendChild(head);

    block.appendChild(rangeField("不透明度", layer.opacity, 0, 1, 0.05,
      (v) => patchLayer(layer.id, { opacity: v })));
    block.appendChild(selectField("合成", layer.blend,
      [["normal", "通常"], ["add", "加算 (発光)"]],
      (v) => patchLayer(layer.id, { blend: v })));
    block.appendChild(selectField("終端の扱い", layer.after_end,
      [["hold", "最後のコマを保持"], ["loop", "ループ"], ["hide", "非表示"]],
      (v) => patchLayer(layer.id, { after_end: v })));
    block.appendChild(numberField("開始位置 (ms)", layer.start_ticks, 0, 600000, 10,
      (v) => patchLayer(layer.id, { start_ticks: fh(v) })));
    block.appendChild(toggleField("表示", layer.visible,
      (v) => patchLayer(layer.id, { visible: v })));
    return block;
  }

  function exposureBlock(exposure) {
    const block = document.createElement("section");
    block.className = "insp-block";
    const head = document.createElement("div");
    head.className = "insp-head";
    const h4 = document.createElement("h4");
    h4.textContent = "選択中のコマ" + (info.count > 1 ? `（${info.count}コマ選択中）` : "");
    head.appendChild(h4);
    block.appendChild(head);

    block.appendChild(numberField("表示時間 (ms)", exposure.hold_ticks, 10, 60000, 10,
      (v) => patchExposure(exposure.id, { hold_ticks: fh(v) })));
    block.appendChild(pairField("位置 dx / dy", exposure.dx, exposure.dy,
      (dx, dy) => patchExposure(exposure.id, { dx: fh(dx), dy: fh(dy) })));
    block.appendChild(numberField("倍率 (%)", fh((exposure.scale || 1) * 100), 5, 800, 5,
      (v) => patchExposure(exposure.id, { scale: Math.min(8, Math.max(0.05, v / 100)) })));
    block.appendChild(toggleField("左右反転", exposure.flip_x,
      (v) => patchExposure(exposure.id, { flip_x: v })));
    const editBtn = document.createElement("button");
    editBtn.type = "button";
    editBtn.className = "btn insp-edit-btn";
    editBtn.textContent = "プレビュー上で移動・拡大縮小";
    editBtn.title = "コマをダブルクリック →「編集」でも開けます";
    editBtn.addEventListener("click", () => { if (cb.onStartEdit) cb.onStartEdit(exposure.id); });
    block.appendChild(editBtn);
    block.appendChild(selectField("透過処理", exposure.matte_mode,
      [["inherit", "レイヤー設定を継承"], ["override", "このコマだけ上書き"], ["skip", "かけない (透過済み)"]],
      (v) => patchExposure(exposure.id, { matte_mode: v })));

    const drop = document.createElement("label");
    drop.className = "insp-drop";
    drop.innerHTML = '<span>画像をドロップ / クリックして差し替え</span>'
      + '<small>Undo対象外です</small>';
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/*";
    input.hidden = true;
    input.addEventListener("change", () => {
      if (input.files[0] && cb.onReplaceImage) cb.onReplaceImage(exposure.id, input.files[0]);
    });
    drop.appendChild(input);
    drop.addEventListener("dragover", (ev) => { ev.preventDefault(); drop.classList.add("over"); });
    drop.addEventListener("dragleave", () => drop.classList.remove("over"));
    drop.addEventListener("drop", (ev) => {
      ev.preventDefault();
      drop.classList.remove("over");
      const f = ev.dataTransfer.files[0];
      if (f && cb.onReplaceImage) cb.onReplaceImage(exposure.id, f);
    });
    block.appendChild(drop);
    return block;
  }

  /**
   * 編集モード(transformedit.js)のパネル。st = TransformEdit.get()。
   * ドラッグ中に呼ばれても、入力中の欄は作り直さず値だけ追従させる(フォーカスを奪わない)。
   */
  function renderTransform(st) {
    if (!container || !st) return;
    const active = document.activeElement;
    const existing = container.querySelector(".xf-block");
    if (existing && active && container.contains(active) && active.tagName === "INPUT") {
      existing.querySelectorAll("[data-xf]").forEach((inp) => {
        if (inp !== active) inp.value = xfValue(st, inp.dataset.xf);
      });
      existing.querySelectorAll("[data-xf-out]").forEach((o) => { o.textContent = st.seeThrough + "%"; });
      return;
    }
    container.innerHTML = "";
    const block = document.createElement("section");
    block.className = "insp-block xf-block";
    const head = document.createElement("div");
    head.className = "insp-head";
    const h4 = document.createElement("h4");
    h4.textContent = "編集モード — 位置・倍率";
    head.appendChild(h4);
    block.appendChild(head);

    // コマ送り(編集を続けたまま前後のコマへ。変更は確定までまとめて保持)
    const nav = document.createElement("div");
    nav.className = "xf-nav";
    const prev = actionButton("◀ 前のコマ", "prev");
    prev.disabled = st.pos <= 1;
    prev.title = "前のコマ ( , キー)";
    const label = document.createElement("span");
    label.className = "mono xf-pos";
    label.textContent = "コマ " + st.pos + " / " + st.count;
    const next = actionButton("次のコマ ▶", "next");
    next.disabled = st.pos >= st.count;
    next.title = "次のコマ ( . キー)";
    nav.append(prev, label, next);
    block.appendChild(nav);

    // 透明度(表示のみ・保存しない)。上げると後ろの前のコマが見える
    const see = fieldWrap("透明度（前のコマを透かす）");
    const seeBox = document.createElement("div");
    seeBox.className = "insp-range";
    const seeIn = document.createElement("input");
    seeIn.type = "range";
    seeIn.min = 0; seeIn.max = 100; seeIn.step = 5;
    seeIn.value = st.seeThrough;
    seeIn.dataset.xf = "seeThrough";
    const seeOut = document.createElement("span");
    seeOut.className = "mono";
    seeOut.dataset.xfOut = "seeThrough";
    seeOut.textContent = st.seeThrough + "%";
    seeIn.addEventListener("input", () => transform({ seeThrough: Number(seeIn.value) }));
    seeBox.append(seeIn, seeOut);
    see.appendChild(seeBox);
    see.title = "編集中の表示だけに使います（保存されません）";
    block.appendChild(see);

    const pos = pairField("位置 X / Y", st.draft.dx, st.draft.dy,
      (x, y) => transform({ dx: x, dy: y }));
    const posInputs = pos.querySelectorAll("input");
    posInputs[0].dataset.xf = "dx";
    posInputs[1].dataset.xf = "dy";
    block.appendChild(pos);
    const sc = numberField("倍率 (%)", xfValue(st, "scale"), 5, 800, 5,
      (v) => transform({ scale: v / 100 }));
    sc.querySelector("input").dataset.xf = "scale";
    block.appendChild(sc);

    const tools = document.createElement("div");
    tools.className = "insp-actions";
    tools.append(actionButton("等倍に戻す", "reset"), actionButton("中央揃え", "center"));
    block.appendChild(tools);

    block.appendChild(selectField("適用範囲", st.scope, [
      ["one", "このコマだけ"],
      ["selected", "選択中の " + st.selectedCount + " コマ"],
      ["layer", "レイヤーの全コマ"],
    ], (v) => transform({ scope: v })));
    const help = document.createElement("p");
    help.className = "insp-help";
    help.textContent = "枠をドラッグで移動、四隅で拡大縮小、ホイールで倍率、矢印キーで1px（Shiftで10px）。"
      + " , / . キーでコマ送り。移動は差分、倍率は同じ値を適用範囲に反映します。"
      + "コマ送りしながら直した分は「確定」でまとめて保存されます。";
    block.appendChild(help);

    const foot = document.createElement("div");
    foot.className = "insp-actions";
    const ok = actionButton("確定 (Enter)", "commit");
    ok.classList.add("btn-primary");
    foot.append(ok, actionButton("キャンセル (Esc)", "cancel"));
    block.appendChild(foot);
    container.appendChild(block);
  }

  function xfValue(st, key) {
    if (key === "scale") return fh(st.draft.scale * 100);
    if (key === "seeThrough") return st.seeThrough;
    return st.draft[key];
  }
  function transform(patch) { if (cb.onTransform) cb.onTransform(patch); }
  function actionButton(label, name) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "btn";
    b.textContent = label;
    b.addEventListener("click", () => { if (cb.onTransformAction) cb.onTransformAction(name); });
    return b;
  }

  function patchLayer(id, patch) { if (cb.onLayerPatch) cb.onLayerPatch(id, patch); }
  function patchExposure(id, patch) { if (cb.onExposurePatch) cb.onExposurePatch(id, patch); }

  // ---- field builders ----

  function fieldWrap(labelText) {
    const wrap = document.createElement("div");
    wrap.className = "insp-field";
    const lab = document.createElement("label");
    lab.textContent = labelText;
    // 狭いパネルではラベルが省略されるので、フルのテキストをツールチップで残す
    lab.title = labelText;
    wrap.appendChild(lab);
    return wrap;
  }

  function numberField(labelText, value, min, max, step, onCommit) {
    const wrap = fieldWrap(labelText);
    const inp = document.createElement("input");
    inp.type = "number";
    inp.className = "insp-input mono";
    inp.value = value;
    inp.min = min; inp.max = max; inp.step = step;
    inp.addEventListener("change", () => {
      const v = parseFloat(inp.value);
      if (!Number.isNaN(v)) onCommit(v);
    });
    wrap.appendChild(inp);
    return wrap;
  }

  function pairField(labelText, v1, v2, onCommit) {
    const wrap = fieldWrap(labelText);
    const pair = document.createElement("div");
    pair.className = "insp-pair";
    const a = document.createElement("input");
    const b = document.createElement("input");
    [a, b].forEach((el, i) => {
      el.type = "number";
      el.className = "insp-input mono";
      el.value = i === 0 ? v1 : v2;
      el.step = 1;
      el.addEventListener("change", () => {
        const av = parseFloat(a.value), bv = parseFloat(b.value);
        if (!Number.isNaN(av) && !Number.isNaN(bv)) onCommit(av, bv);
      });
      pair.appendChild(el);
    });
    wrap.appendChild(pair);
    return wrap;
  }

  function rangeField(labelText, value, min, max, step, onCommit) {
    const wrap = fieldWrap(labelText);
    const box = document.createElement("div");
    box.className = "insp-range";
    const inp = document.createElement("input");
    inp.type = "range";
    inp.min = min; inp.max = max; inp.step = step;
    inp.value = value;
    const out = document.createElement("span");
    out.className = "mono";
    out.textContent = Number(value).toFixed(2);
    inp.addEventListener("input", () => { out.textContent = Number(inp.value).toFixed(2); });
    inp.addEventListener("change", () => onCommit(parseFloat(inp.value)));
    box.appendChild(inp);
    box.appendChild(out);
    wrap.appendChild(box);
    return wrap;
  }

  function selectField(labelText, value, options, onCommit) {
    const wrap = fieldWrap(labelText);
    const sel = document.createElement("select");
    sel.className = "insp-input";
    for (const opt of options) {
      const [val, text] = Array.isArray(opt) ? opt : [opt, opt];
      const o = document.createElement("option");
      o.value = val; o.textContent = text;
      if (val === value) o.selected = true;
      sel.appendChild(o);
    }
    sel.addEventListener("change", () => onCommit(sel.value));
    wrap.appendChild(sel);
    return wrap;
  }

  function toggleField(labelText, on, onCommit) {
    const wrap = fieldWrap(labelText);
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "insp-toggle" + (on ? " on" : "");
    btn.setAttribute("aria-pressed", on ? "true" : "false");
    btn.addEventListener("click", () => onCommit(!on));
    wrap.appendChild(btn);
    return wrap;
  }

  function iconButton(title, pathMarkup) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "icon-btn";
    btn.title = title;
    btn.setAttribute("aria-label", title);
    btn.innerHTML = '<svg class="icon" viewBox="0 0 20 20">' + pathMarkup + "</svg>";
    return btn;
  }

  return { attach: attach, render: render, renderTransform: renderTransform };
})();
