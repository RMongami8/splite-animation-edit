/*
 * 再生クロック。描画(canvasview.js)とは独立に時刻(tick)だけを進める。
 * rate はプレビューの再生速度(×0.5 など)で、データや書き出しには影響しない。
 */
const Player = (() => {
  "use strict";
  let playing = false;
  let startPerf = 0;
  let currentTicks = 0;
  let rate = 1;
  let totalTicksFn = () => 0;
  const listeners = [];

  function onTick(fn) { listeners.push(fn); }
  function notify() { listeners.forEach((fn) => fn(currentTicks)); }
  function setTotalTicksFn(fn) { totalTicksFn = fn; }

  // 現在の tick と速度から、実時間の基準点を取り直す(速度変更・シーク時に位置を飛ばさない)
  function anchor() { startPerf = performance.now() - currentTicks / rate; }

  function play() {
    playing = true;
    anchor();
  }
  function pause() { playing = false; }
  function toggle() { if (playing) pause(); else play(); }
  function seek(t) {
    currentTicks = Math.max(0, t);
    anchor();
    notify();
  }
  function setRate(r) {
    rate = r > 0 ? r : 1;
    anchor();
  }

  function tickLoop(now) {
    if (playing) {
      const total = totalTicksFn();
      currentTicks = total > 0 ? ((now - startPerf) * rate) % total : 0;
      notify();
    }
    requestAnimationFrame(tickLoop);
  }
  requestAnimationFrame(tickLoop);

  return {
    onTick, play, pause, toggle, seek, setTotalTicksFn, setRate,
    isPlaying: () => playing, getTicks: () => currentTicks, getRate: () => rate,
  };
})();
