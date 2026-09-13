/*
 * 合成式（プラン §6 準拠）。core/composite.py と1対1対応させる。
 * ブラウザでは <script src="composite.js"> で読み込み window.SSComposite を使う。
 * Node (selftest_parity 用) では require()/module.exports で同じ関数を使う。
 *
 * 規則: floor(x+0.5) のみ使う。Math.round() は使わない
 * （半数の丸め方向が Python の round() と食い違うため）。
 */
(function (root, factory) {
  var mod = factory();
  if (typeof module !== "undefined" && module.exports) {
    module.exports = mod;
  } else {
    root.SSComposite = mod;
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  function floorHalf(x) {
    return Math.floor(x + 0.5);
  }

  function clamp255(x) {
    return x < 0 ? 0 : x > 255 ? 255 : x;
  }

  /**
   * dst, src: Uint8ClampedArray/Uint8Array 長さ w*h*4 (RGBA, ストレートアルファ)。
   * 戻り値: 新しい Uint8ClampedArray(w*h*4)。
   */
  function blendNormal(dst, src, opacity, w, h) {
    var out = new Uint8ClampedArray(w * h * 4);
    for (var i = 0; i < w * h; i++) {
      var o = i * 4;
      var a = (src[o + 3] / 255) * opacity;
      for (var c = 0; c < 3; c++) {
        var s = src[o + c];
        var d = dst[o + c];
        out[o + c] = clamp255(floorHalf(s * a + d * (1 - a)));
      }
      var dstA = dst[o + 3] / 255;
      out[o + 3] = clamp255(floorHalf((a + dstA * (1 - a)) * 255));
    }
    return out;
  }

  /** 発光素材の加算合成。src の RGB を発光量として dst に加算する。 */
  function blendAdd(dst, src, opacity, w, h) {
    var out = new Uint8ClampedArray(w * h * 4);
    for (var i = 0; i < w * h; i++) {
      var o = i * 4;
      var r = src[o], g = src[o + 1], b = src[o + 2];
      for (var c = 0; c < 3; c++) {
        var add = floorHalf(src[o + c] * opacity);
        out[o + c] = clamp255(dst[o + c] + add);
      }
      var luma = floorHalf((299 * r + 587 * g + 114 * b) / 1000);
      out[o + 3] = Math.max(dst[o + 3], clamp255(floorHalf(luma * opacity)));
    }
    return out;
  }

  /**
   * box filter（面積平均）による縮小専用リサイズ。Python 側 PIL Image.BOX と
   * 同じ考え方（各出力ピクセルは対応する入力矩形領域の単純平均）に固定する。
   * 拡大には使わない想定。
   */
  function resizeBox(src, srcW, srcH, dstW, dstH) {
    var out = new Uint8ClampedArray(dstW * dstH * 4);
    var scaleX = srcW / dstW;
    var scaleY = srcH / dstH;
    for (var oy = 0; oy < dstH; oy++) {
      var sy0 = Math.floor(oy * scaleY);
      var sy1 = Math.max(sy0 + 1, Math.floor((oy + 1) * scaleY));
      sy1 = Math.min(sy1, srcH);
      for (var ox = 0; ox < dstW; ox++) {
        var sx0 = Math.floor(ox * scaleX);
        var sx1 = Math.max(sx0 + 1, Math.floor((ox + 1) * scaleX));
        sx1 = Math.min(sx1, srcW);
        var sums = [0, 0, 0, 0];
        var count = 0;
        for (var yy = sy0; yy < sy1; yy++) {
          for (var xx = sx0; xx < sx1; xx++) {
            var so = (yy * srcW + xx) * 4;
            sums[0] += src[so]; sums[1] += src[so + 1];
            sums[2] += src[so + 2]; sums[3] += src[so + 3];
            count++;
          }
        }
        var oo = (oy * dstW + ox) * 4;
        for (var c2 = 0; c2 < 4; c2++) {
          out[oo + c2] = clamp255(floorHalf(sums[c2] / count));
        }
      }
    }
    return out;
  }

  return { floorHalf: floorHalf, clamp255: clamp255, blendNormal: blendNormal,
           blendAdd: blendAdd, resizeBox: resizeBox };
});
