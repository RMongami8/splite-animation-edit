// selftest_parity.py から呼ばれる Node ドライバ。
// dst.bin / src.bin (RGBA raw bytes) を読み、composite.js の blendNormal/blendAdd を
// 実行して結果を normal_js.bin / add_js.bin に書き出す。
// 引数: dstPath srcPath w h opacity outDir
const fs = require("fs");
const path = require("path");
const SSComposite = require(path.join(__dirname, "..", "web", "static", "js", "composite.js"));

const [, , dstPath, srcPath, wStr, hStr, opStr, outDir] = process.argv;
const w = parseInt(wStr, 10);
const h = parseInt(hStr, 10);
const opacity = parseFloat(opStr);

const dst = new Uint8ClampedArray(fs.readFileSync(dstPath));
const src = new Uint8ClampedArray(fs.readFileSync(srcPath));

const normalOut = SSComposite.blendNormal(dst, src, opacity, w, h);
const addOut = SSComposite.blendAdd(dst, src, opacity, w, h);

fs.writeFileSync(path.join(outDir, "normal_js.bin"), Buffer.from(normalOut));
fs.writeFileSync(path.join(outDir, "add_js.bin"), Buffer.from(addOut));
