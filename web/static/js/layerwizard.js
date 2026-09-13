/*
 * レイヤー追加ウィザード(#layerModal)。素材のどのコマを使うかを選んでからレイヤーにする。
 *
 * 抽出方法: 全フレーム / N枚ごと / 枚数を指定して均等 / 動きの変化で自動 / 手動。
 * 方法を選ぶと採用コマ(✓)が一覧に入り、一覧のクリックで手直しできる(手直しすると「手動」)。
 * 「動きの変化で自動」は GET /api/assets/{id}/frame_scores(直前との差分)を1回だけ取り、
 * 最後に採用したコマからの差分の累積がしきい値を超えたら採用する。
 *
 * 表示時間の見積もりはサーバー(routes_edit._holds_from_asset_frames)と同じ規則で計算する。
 * 丸めは floor(x+0.5)(CLAUDE.md 規則3)。
 */
const LayerWizard = (() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const fh = (x) => Math.floor(x + 0.5);
  const STATIC_HOLD = 1000;   // routes_edit.CreateLayerBody.static_hold_ticks の既定値
  let asset = null;
  let frames = [];
  let scores = null;
  let picked = new Set();     // frames 配列の位置
  let thumbs = [];
  let lastClick = null;
  let bound = false;

  function bind() {
    if (bound) return;
    bound = true;
    document.querySelectorAll('input[name="lwMethod"]').forEach((r) => r.addEventListener("change", onMethod));
    ["lwStart", "lwEnd", "lwEveryN", "lwCount", "lwThresh"].forEach((id) => $(id).addEventListener("input", recompute));
    $("lwIncludeLast").addEventListener("change", recompute);
    document.querySelectorAll('input[name="lwHold"]').forEach((r) => r.addEventListener("change", updateSummary));
    $("lyLastHold").addEventListener("input", updateSummary);
    $("lwFixedMs").addEventListener("input", () => { $("lwFps").value = ""; updateSummary(); });
    $("lwFps").addEventListener("input", () => {
      const fps = Number($("lwFps").value);
      if (fps > 0) $("lwFixedMs").value = fh(1000 / fps);
      updateSummary();
    });
  }

  function method() { return document.querySelector('input[name="lwMethod"]:checked').value; }
  function holdMode() { return document.querySelector('input[name="lwHold"]:checked').value; }
  function setMethod(v) { document.querySelector(`input[name="lwMethod"][value="${v}"]`).checked = true; showParams(); }

  function showParams() {
    const m = method();
    $("lwParamEvery").hidden = m !== "every";
    $("lwParamCount").hidden = m !== "count";
    $("lwParamAuto").hidden = m !== "auto";
  }

  async function open(a) {
    bind();
    asset = a;
    scores = null;
    lastClick = null;
    frames = await State.getAssetFrames(a.id);
    $("lwAssetName").textContent = "素材 " + a.kind + " · " + frames.length + "コマ · " + a.width + "×" + a.height;
    $("lwStart").max = $("lwEnd").max = frames.length;
    $("lwStart").value = 1;
    $("lwEnd").value = frames.length;
    $("lwCount").max = frames.length;
    $("lyLastHold").value = "";
    setMethod("all");
    document.querySelector('input[name="lwHold"][value="source"]').checked = true;
    buildGrid();
    recompute();
  }

  function range() {
    const n = frames.length;
    let s = Math.min(n, Math.max(1, parseInt($("lwStart").value, 10) || 1)) - 1;
    let e = Math.min(n, Math.max(1, parseInt($("lwEnd").value, 10) || n)) - 1;
    if (s > e) { const t = s; s = e; e = t; }
    return { s: s, e: e };
  }

  async function onMethod() {
    showParams();
    if (method() === "auto" && !scores && asset) {
      $("lwAutoNote").textContent = "動きの差分を計算中…";
      const forAsset = asset.id;
      try {
        const res = await Api.getFrameScores(forAsset);
        if (asset && asset.id === forAsset) scores = res.scores;
        $("lwAutoNote").textContent = "";
      } catch (err) {
        $("lwAutoNote").textContent = "差分を計算できませんでした";
        console.error(err);
      }
    }
    recompute();
  }

  function compute(m, s, e) {
    const out = [];
    if (m === "all") {
      for (let i = s; i <= e; i++) out.push(i);
    } else if (m === "every") {
      const n = Math.max(1, parseInt($("lwEveryN").value, 10) || 1);
      for (let i = s; i <= e; i += n) out.push(i);
    } else if (m === "count") {
      const len = e - s + 1;
      const k = Math.min(len, Math.max(1, parseInt($("lwCount").value, 10) || 1));
      if (k === 1) out.push(s);
      else for (let j = 0; j < k; j++) out.push(s + fh(j * (len - 1) / (k - 1)));
    } else if (m === "auto") {
      out.push(s);
      if (scores) {
        const th = Number($("lwThresh").value);
        let acc = 0;
        for (let i = s + 1; i <= e; i++) {
          acc += scores[i] || 0;
          if (acc >= th) { out.push(i); acc = 0; }
        }
      }
      if ($("lwIncludeLast").checked && out[out.length - 1] !== e) out.push(e);
    }
    return out;
  }

  function recompute() {
    $("lwThreshVal").textContent = Number($("lwThresh").value).toFixed(3);
    const r = range();
    const m = method();
    if (m === "manual") {
      picked = new Set([...picked].filter((i) => i >= r.s && i <= r.e));
    } else {
      picked = new Set(compute(m, r.s, r.e));
    }
    paintGrid();
    updateSummary();
  }

  function buildGrid() {
    const grid = $("lwGrid");
    grid.innerHTML = "";
    thumbs = frames.map((f, i) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "lw-thumb";
      b.title = "コマ " + (i + 1);
      const img = document.createElement("img");
      img.loading = "lazy";
      img.alt = "";
      img.src = f.thumb_url;
      const n = document.createElement("span");
      n.className = "n mono";
      n.textContent = i + 1;
      const ck = document.createElement("span");
      ck.className = "ck";
      ck.textContent = "✓";
      b.append(img, n, ck);
      b.addEventListener("click", (ev) => onThumb(i, ev.shiftKey));
      grid.appendChild(b);
      return b;
    });
  }

  function onThumb(i, shift) {
    const r = range();
    if (i < r.s || i > r.e) return;
    const turnOn = !picked.has(i);
    if (shift && lastClick !== null) {
      const a = Math.max(r.s, Math.min(lastClick, i)), b = Math.min(r.e, Math.max(lastClick, i));
      for (let j = a; j <= b; j++) { if (turnOn) picked.add(j); else picked.delete(j); }
    } else if (turnOn) {
      picked.add(i);
    } else {
      picked.delete(i);
    }
    lastClick = i;
    setMethod("manual");
    paintGrid();
    updateSummary();
  }

  function paintGrid() {
    const r = range();
    thumbs.forEach((b, i) => {
      b.classList.toggle("on", picked.has(i));
      b.classList.toggle("out", i < r.s || i > r.e);
    });
  }

  function ticksOf(f) {
    const num = f.pts * asset.tb_num * 1000, den = asset.tb_den;
    return Math.floor((2 * num + den) / (2 * den));   // floor(pts*tb*1000 + 0.5)
  }

  function sortedPicked() { return [...picked].sort((a, b) => a - b); }

  function estimateHolds() {
    const sel = sortedPicked();
    if (!sel.length) return [];
    const r = range();
    if (holdMode() === "fixed") {
      const ms = Math.max(1, parseInt($("lwFixedMs").value, 10) || 1);
      return sel.map(() => ms);
    }
    if (asset.tb_num == null || asset.tb_den == null || r.e === r.s) return sel.map(() => STATIC_HOLD);
    const lastRaw = $("lyLastHold").value;
    const lastHold = lastRaw !== "" ? Number(lastRaw) : ticksOf(frames[r.e]) - ticksOf(frames[r.e - 1]);
    const end = ticksOf(frames[r.e]) + lastHold;
    return sel.map((i, k) => (k + 1 < sel.length ? ticksOf(frames[sel[k + 1]]) : end) - ticksOf(frames[i]));
  }

  function updateSummary() {
    $("lwHoldSource").hidden = holdMode() !== "source";
    $("lwHoldFixed").hidden = holdMode() !== "fixed";
    if (!asset) return;
    const holds = estimateHolds();
    const total = holds.reduce((a, b) => a + b, 0);
    const sec = (total / 1000).toFixed(2);
    const fps = total > 0 ? (holds.length / (total / 1000)).toFixed(1) : "0";
    $("lwSummary").textContent = holds.length + "コマ使用（全" + frames.length + "コマ中）· 再生時間 "
      + sec + "秒 · 平均 " + fps + "コマ/秒";
    $("lwHoldExplain").textContent = explainHold(holds);
    $("lyCreate").disabled = holds.length === 0;
  }

  /** ③の選択肢が今の設定で何を意味するかを、具体的な数字で説明する。 */
  function explainHold(holds) {
    if (!holds.length) return "採用するコマがありません。";
    const r = range();
    const inRange = r.e - r.s + 1;
    const ms = holds.length ? Math.floor(holds.reduce((a, b) => a + b, 0) / holds.length + 0.5) : 0;
    if (holdMode() === "fixed") {
      return "すべてのコマを " + holds[0] + "ms ずつ表示します。コマを減らすほど全体の再生時間が短く（速く）なります。";
    }
    if (asset.tb_num == null || asset.tb_den == null) {
      return "静止画の素材なので、1コマを " + holds[0] + "ms 表示します。";
    }
    if (holds.length === inRange) {
      return "元の動画のタイミングをそのまま使います（1コマ約 " + ms + "ms）。";
    }
    const ratio = (inRange / holds.length).toFixed(1);
    return "間引いたコマの時間は、その直前に残したコマを長く表示して埋めます。"
      + "動きの速さと全体の長さは元の動画のままで、1コマあたりは平均約" + ratio + "倍（約 " + ms + "ms）になります。";
  }

  /** POST /api/comps/{id}/layers に足す抽出パラメータ。採用0コマなら null。 */
  function getRequest() {
    const sel = sortedPicked();
    if (!asset || !sel.length) return null;
    const r = range();
    const req = {
      frame_start_idx: frames[r.s].idx,
      frame_end_idx: frames[r.e].idx,
      frame_indices: sel.length === r.e - r.s + 1 ? null : sel.map((i) => frames[i].idx),
      hold_mode: holdMode(),
      fixed_hold_ticks: Math.max(1, parseInt($("lwFixedMs").value, 10) || 100),
    };
    if (holdMode() === "source" && $("lyLastHold").value !== "") {
      req.last_hold_ticks = Number($("lyLastHold").value);
    }
    return req;
  }

  return { open: open, getRequest: getRequest };
})();
