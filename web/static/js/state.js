/*
 * アプリ状態(現在のComposition・選択中Layer/Exposure・Asset一覧)の単一のソース。
 * サーバー(DB)が真実であり、ここはその最新スナップショットをキャッシュするだけ
 * (再読み込みで loadComp() すれば復元できる = 編集の再開)。
 *
 * コマの選択は1レイヤー内の複数選択(selectedIds)と、主選択(selectedExposureId =
 * インスペクターに出るコマ)、範囲選択の起点(anchorId)を持つ。deleteMode は
 * タイムラインの削除モード(✕印を出してなぞり選択する)。
 *
 * localStorage に置くのは「直近に開いたCompositionの一覧」だけ。§4 に
 * Composition一覧APIが無いため、この端末で開いたものを思い出すための便利機能で
 * あり、データの真実はあくまでDB側にある。
 */
const State = (() => {
  "use strict";
  const RECENT_KEY = "sss_recent_comps";
  let comp = null;
  let selectedLayerId = null;
  let selectedExposureId = null;
  let selectedIds = new Set();
  let anchorId = null;
  let deleteMode = false;
  let assets = [];
  const framesCache = new Map();
  const listeners = [];

  function onChange(fn) { listeners.push(fn); }
  function notify() { listeners.forEach((fn) => fn()); }

  function clearSelection() {
    selectedExposureId = null;
    selectedIds = new Set();
    anchorId = null;
    deleteMode = false;
  }

  /** 再取得後、消えたコマを選択から外す。 */
  function pruneSelection() {
    if (!comp.layers.find((l) => l.id === selectedLayerId)) {
      selectedLayerId = comp.layers.length ? comp.layers[0].id : null;
      clearSelection();
      return;
    }
    const ly = getSelectedLayer();
    const alive = new Set(ly.exposures.map((e) => e.id));
    selectedIds = new Set([...selectedIds].filter((id) => alive.has(id)));
    if (selectedExposureId && !alive.has(selectedExposureId)) {
      selectedExposureId = selectedIds.size ? [...selectedIds][0] : null;
    }
    if (anchorId && !alive.has(anchorId)) anchorId = selectedExposureId;
  }

  async function loadComp(compId) {
    comp = await Api.getComp(compId);
    rememberComp(comp.id, comp.name);
    pruneSelection();
    notify();
    return comp;
  }

  async function refreshComp() {
    if (!comp) return null;
    comp = await Api.getComp(comp.id);
    pruneSelection();
    notify();
    return comp;
  }

  function closeComp() {
    comp = null;
    selectedLayerId = null;
    clearSelection();
    notify();
  }

  /** Asset 一覧を取り、各Assetの先頭フレームをサムネイルとして付ける。 */
  async function refreshAssets() {
    const res = await Api.listAssets();
    const list = res.assets;
    await Promise.all(list.map(async (a) => {
      try {
        const frames = await getAssetFrames(a.id);
        a.thumb_url = frames.length ? frames[0].thumb_url : null;
      } catch (e) {
        a.thumb_url = null;
      }
    }));
    assets = list;
    notify();
    return assets;
  }

  async function getAssetFrames(assetId) {
    if (framesCache.has(assetId)) return framesCache.get(assetId);
    const res = await Api.getAssetFrames(assetId);
    framesCache.set(assetId, res.frames);
    return res.frames;
  }

  function selectLayer(id) {
    selectedLayerId = id;
    clearSelection();
    notify();
  }

  /**
   * mods.ctrl = 追加/解除、mods.shift = anchor からの範囲。別レイヤーのコマを
   * 選ぶと選択はそのレイヤーだけに切り替わる。
   */
  function selectExposure(layerId, expId, mods) {
    mods = mods || {};
    if (layerId !== selectedLayerId) {
      selectedLayerId = layerId;
      selectedIds = new Set();
      anchorId = null;
    }
    const ly = getSelectedLayer();
    if (mods.shift && anchorId && ly) {
      const ids = ly.exposures.map((e) => e.id);
      const a = ids.indexOf(anchorId), b = ids.indexOf(expId);
      selectedIds = new Set(ids.slice(Math.min(a, b), Math.max(a, b) + 1));
      selectedExposureId = expId;
    } else if (mods.ctrl) {
      if (selectedIds.has(expId)) {
        selectedIds.delete(expId);
        selectedExposureId = selectedExposureId === expId
          ? ([...selectedIds].pop() || null) : selectedExposureId;
      } else {
        selectedIds.add(expId);
        selectedExposureId = expId;
      }
      anchorId = expId;
    } else {
      selectedIds = new Set([expId]);
      selectedExposureId = expId;
      anchorId = expId;
    }
    notify();
  }

  function setSelection(layerId, ids, primaryId) {
    selectedLayerId = layerId;
    selectedIds = new Set(ids);
    selectedExposureId = primaryId && selectedIds.has(primaryId) ? primaryId : (ids[0] || null);
    anchorId = selectedExposureId;
    notify();
  }

  function setDeleteMode(on) {
    deleteMode = !!on;
    notify();
  }

  function getComp() { return comp; }
  function getAssets() { return assets; }
  function getSelectedLayer() {
    if (!comp) return null;
    return comp.layers.find((l) => l.id === selectedLayerId) || null;
  }
  function getSelectedExposure() {
    const ly = getSelectedLayer();
    if (!ly) return null;
    return ly.exposures.find((e) => e.id === selectedExposureId) || null;
  }
  /** 選択中コマのID(レイヤー内の並び順)。 */
  function getSelectedIds() {
    const ly = getSelectedLayer();
    if (!ly) return [];
    return ly.exposures.filter((e) => selectedIds.has(e.id)).map((e) => e.id);
  }
  function getLayerById(id) {
    if (!comp) return null;
    return comp.layers.find((l) => l.id === id) || null;
  }

  // ---- 直近に開いたComposition ----

  function getRecentComps() {
    try {
      const raw = localStorage.getItem(RECENT_KEY);
      return raw ? JSON.parse(raw) : [];
    } catch (e) {
      return [];
    }
  }

  function rememberComp(id, name) {
    try {
      const list = getRecentComps().filter((c) => c.id !== id);
      list.unshift({ id: id, name: name, at: Date.now() });
      localStorage.setItem(RECENT_KEY, JSON.stringify(list.slice(0, 12)));
    } catch (e) { /* プライベートモード等では黙って諦める */ }
  }

  function forgetComp(id) {
    try {
      localStorage.setItem(RECENT_KEY, JSON.stringify(getRecentComps().filter((c) => c.id !== id)));
    } catch (e) { /* ignore */ }
  }

  return {
    onChange: onChange, notify: notify,
    loadComp: loadComp, refreshComp: refreshComp, closeComp: closeComp,
    refreshAssets: refreshAssets, getAssetFrames: getAssetFrames,
    selectLayer: selectLayer, selectExposure: selectExposure, setSelection: setSelection,
    setDeleteMode: setDeleteMode, isDeleteMode: () => deleteMode,
    getComp: getComp, getAssets: getAssets,
    getSelectedLayer: getSelectedLayer, getSelectedExposure: getSelectedExposure,
    getSelectedIds: getSelectedIds, getLayerById: getLayerById,
    getRecentComps: getRecentComps, rememberComp: rememberComp, forgetComp: forgetComp,
  };
})();
