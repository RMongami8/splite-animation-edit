/*
 * Undo/Redo スタック(コマンドパターン)。プラン §1「Undo/Redo・自動保存は初期実装に
 * 含める」に対応する。自動保存そのものは各編集APIが同期的に即時書き込みする
 * ため別途タイマーは不要(=編集操作そのものが自動保存)。ここは「元に戻す/やり直す」
 * 操作列の管理だけを担当する。
 *
 * 既知の制約(M1): POST /api/exposures/{id}/replace(画像差し替え)は新規Assetを
 * 作る一方向の操作で、PATCH /api/exposures/{id} には asset_id/frame_id を戻す
 * 手段が無いため、Undo対象に含めない(押した時点でスタックに積まない)。
 */
const History = (() => {
  "use strict";
  let undoStack = [];
  let redoStack = [];
  let onChange = () => {};

  function init(cb) {
    onChange = cb;
  }

  async function run(cmd) {
    // cmd = {label, do: async()=>void, undo: async()=>void}
    await cmd.do();
    undoStack.push(cmd);
    redoStack = [];
    onChange();
  }

  async function undo() {
    const cmd = undoStack.pop();
    if (!cmd) return;
    await cmd.undo();
    redoStack.push(cmd);
    onChange();
  }

  async function redo() {
    const cmd = redoStack.pop();
    if (!cmd) return;
    await cmd.do();
    undoStack.push(cmd);
    onChange();
  }

  function canUndo() { return undoStack.length > 0; }
  function canRedo() { return redoStack.length > 0; }
  function clear() { undoStack = []; redoStack = []; onChange(); }

  return { init, run, undo, redo, canUndo, canRedo, clear };
})();
