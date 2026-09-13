# 作業ルール

## 絶対規則
1. 唯一の仕様書は `C:\Users\blood\.claude\plans\1-ai-ai-web-git-seedance2-0-gtp-image2-a-wiggly-glade.md`。
   型・DDL・JSONスキーマ・関数シグネチャ・コマンドはそこに書いてある通りに実装する。
2. Spine 本体・Spine SDK・`skeleton.json`・Spine atlas・Spine による検証は実装しない。
   コードに出てきたら削除する。パーツ分割／ボーン推定／メッシュ変形も対象外。
3. 丸めは `floor(x + 0.5)` を使う。`round()` / `Math.round()` を使わない
   （Python の round() は偶数丸め、JS の Math.round() は半数切り上げで結果が食い違うため）。
4. ファイル置換は `os.replace()`（`os.rename` は Windows で既存ファイルがあると失敗する）。
5. テキスト I/O は必ず `encoding="utf-8"`、`json.dump(..., ensure_ascii=False)`。
6. パスは `pathlib.Path`。DB に入れるのは常にプロジェクト相対の posix 文字列（`as_posix()`）。
7. `exposures.ord` に UNIQUE 制約を付けない。並べ替えはコード側で一意性を保証する。
8. アルファはストレート（非乗算）・uint8・sRGB 固定。プリマルチプライにしない。
9. `originals/` は追記のみ。上書き・削除しない。
10. M0〜M3 では `opencv` / `rembg` / `pymupdf` / `scipy` を import しない。
11. 依存を増やすときは実装前にユーザーへ確認する。`requirements.txt` を勝手に増やさない。
12. 画像・base64・APIキーを stdout / ログ / レスポンスに出さない。確認は size/shape/len() のみ。

## トークン節約規則
13. ファイル全体を読み直さない。編集は差分(Edit)で行う。新規作成時のみ全文を書く。
14. 検証は 64×64・8コマのダミー画像で行う。実サイズで試行錯誤しない。
15. 1モジュール実装 → その場で単体検証 → 次へ、の順で進める。全部書いてから一括デバッグしない。
16. エラーが出たら、まず該当モジュールだけを見る。他ファイルを開かない。
17. 完了報告は簡潔に。コードを再掲しない。

## 検証用ダミー素材の作り方
python -m tools.make_dummy
