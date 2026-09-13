/*
 * コマのポップアップメニュー(ダブルクリック/右クリックで開く)。
 * items: [{label, hint, action, danger, disabled} | {sep: true}]
 * 画面内に収まる位置へ出し、Esc・外側クリック・項目実行で閉じる。
 */
const CellMenu = (() => {
  "use strict";
  let el = null;

  function close() {
    if (!el) return;
    el.remove();
    el = null;
    window.removeEventListener("mousedown", onOutside, true);
    window.removeEventListener("blur", close);
  }

  function onOutside(ev) {
    if (el && !el.contains(ev.target)) close();
  }

  function open(x, y, items, title) {
    close();
    el = document.createElement("div");
    el.className = "ctx-menu";
    el.setAttribute("role", "menu");
    if (title) {
      const h = document.createElement("div");
      h.className = "ctx-title";
      h.textContent = title;
      el.appendChild(h);
    }
    for (const it of items) {
      if (it.sep) {
        const s = document.createElement("div");
        s.className = "ctx-sep";
        el.appendChild(s);
        continue;
      }
      const b = document.createElement("button");
      b.type = "button";
      b.className = "ctx-item" + (it.danger ? " danger" : "");
      b.setAttribute("role", "menuitem");
      b.disabled = !!it.disabled;
      const lab = document.createElement("span");
      lab.textContent = it.label;
      b.appendChild(lab);
      if (it.hint) {
        const k = document.createElement("span");
        k.className = "ctx-hint mono";
        k.textContent = it.hint;
        b.appendChild(k);
      }
      b.addEventListener("click", () => { close(); it.action(); });
      el.appendChild(b);
    }
    document.body.appendChild(el);
    const r = el.getBoundingClientRect();
    const left = Math.max(6, Math.min(x, window.innerWidth - r.width - 6));
    const top = Math.max(6, Math.min(y, window.innerHeight - r.height - 6));
    el.style.left = left + "px";
    el.style.top = top + "px";
    const first = el.querySelector(".ctx-item:not(:disabled)");
    if (first) first.focus();
    // 開いたときのクリック自体で閉じないよう、捕捉は次のイベントから
    setTimeout(() => {
      window.addEventListener("mousedown", onOutside, true);
      window.addEventListener("blur", close);
    }, 0);
  }

  return { open: open, close: close, isOpen: () => !!el };
})();
