# 実装判断の記録

プラン本体(`C:\Users\blood\.claude\plans\1-ai-ai-web-git-seedance2-0-gtp-image2-a-wiggly-glade.md`)
に明記が無く、実装時に判断した事項をここに残す。

## M0

- **デコード経路**: `tools/doctor.py` が `import av` 成功を確認済み。以後 `core/video.py`
  (M1) は PyAV を第一経路として実装し、失敗時のみ ffmpeg フォールバックにする
  （プラン §11 の tools/doctor.py 契約通り）。
- **`tools/make_dummy.py` の ID**: `core/ids.py` の `new_id()`（ランダム16進）ではなく、
  固定ID（`cp_dummy`, `ly_dummy_char`, `as_dummy_char` 等）を使う。理由: 複数プロセスから
  起動される `python -m tools.selftest_*` が同じダミーデータを確実に参照できるようにするため、
  かつ再実行時に冪等（既存ダミー行を削除してから作り直す）にするため。本番の Asset/Composition
  生成では引き続き `new_id()` を使う。
- **`core/sheet.py` の配置アンカー**: `build_grid()` はセルを `cell_wh` 枠内で
  **下辺中央（bottom-center）**に配置する固定仕様にした。プランの契約には
  アンカー方式の明記が無かったが、既定 pivot `[0.5, 1.0]`（足元中央）と対応させる
  ため。これにより `common_bbox`（M2, matte.py）で切り出した画像がどのフレームでも
  一貫した原点を持つ前提が成り立つ。
- **`selftest_roundtrip.py` のスコープ**: M0 時点では `pkgio.py`（外部ソフトとの
  ZIP+manifest 往復, §8）も `importers.py`（M1）もまだ無いため、このテストは
  「DB → `core/sheet.py` でシート書き出し → `sheet.json` 読み戻し」という**内部**往復のみ
  を検証する。外部ソフトを経由する往復の検証は M2 で `pkgio.py` 完成後に別途行う
  （プラン §12 完成判定の「ZIP 往復で変更画像を対応するコマへ復元できる」はそちらで担保する）。
- **合成式のクロス言語検証**: この環境に Node.js があったため、`tools/selftest_parity.py`
  は手計算の golden 値ではなく、実際に `web/static/js/composite.js` を Node 経由で実行し
  Python の `core/composite.py` と画素比較する方式にした（`tools/_composite_driver.cjs`）。
  実測の最大差は 1/255（float32 と double の丸め差）で許容値 2/255 以内。
- **`web/static/js/composite.js` の `resizeBox`**: box filter による縮小関数を先に
  用意したが、`selftest_parity.py` の対象からは外した。PIL の `Image.BOX` はピクセル
  中心ベースのアンチエイリアシングを行い、素朴な矩形平均とは丸め方が異なるため、
  厳密一致を要求すると誤って失敗する。縮小補間のクロス言語一致は M1/M2 でブラウザ側の
  実描画パスが固まってから改めて検証する。
- **M0 の「最小プレイヤー」**: `web/static/js/{state,history,player,timeline,canvasview,
  inspector}.js`（M1 以降のフル編集UIのモジュール群）はまだ作らず、`web/static/index.html`
  に最小限のインライン `<script>` で Composition 読み込み・再生・レイヤー表示切替だけを
  実装した。`/api/comps/{id}` と `/api/files/{rel_path}` のみを実装し、§4 の編集系
  フルセット(POST/PUT/PATCH)は M1 で `web/routes_edit.py` 等に実装する。
- **プレビュー起動設定**: ブラウザプレビュー(`preview_start`)はセッションのルート
  ディレクトリ(`D:\00_Claude`)の `.claude/launch.json` を見るため、
  `sprite-sheet-studio` 単体の `.claude/launch.json` は使われない。ルート側の
  `launch.json` に `"sprite-sheet-studio"` という名前で venv の `app.py` 起動設定を
  追記した（既存の `lineart2psd` エントリと共存）。

## M0 完了確認 (2026-09-12)

`python -m tools.doctor` → `make_dummy` → `selftest_time` → `selftest_parity` →
`selftest_roundtrip` を通しで実行し、全PASS。ブラウザプレビューで
`char`(通常合成)/`fx`(加算合成)の2レイヤー再生、レイヤー表示切替、スクラバーの
動作を目視確認済み（スクリーンショット確認済み、コンソール/ネットワークエラー無し）。

## M1

- **`probe_decodable` の落とし穴**: PyAV は静止画(PNG等)も image2 デマルチプレクサ
  経由で「1フレームの動画」として開けてしまう。`n_frames > 1` を動画判定の条件にして
  誤分類を防いだ(`tools/selftest_import.py` で回帰テスト化済み)。
- **`POST /api/assets/import` は multipart にした**: §4 表は「すべてJSON(アップロード
  のみmultipart)」とあるが、連番/シート/studio_sheet/GIFの取り込みは実際のファイル
  バイトを同時に送る必要があり、JSON単体では不可能。`type`/`params_json`をフォーム
  フィールド、ファイルは`file`/`json_file`/`files`のフィールド名で受け取る形にした。
- **originals/ と derived/ の使い分け**: 単一の元ファイルから再現できないもの
  (アップロードされた動画そのもの、連番画像そのもの、シート画像そのもの)は
  `originals/<asset_id>/` へ。原本から再生成できる派生(動画から抽出したフレーム、
  シートから切り出したセル)は `derived/frames/<asset_id>/` へ、と明確に分けた。
  `tools/make_dummy.py`(M0のテスト専用フィクスチャ)は簡略化のため両方とも
  `derived/frames/` に置いているが、これは意図的な例外としてそのまま残す。
- **Asset+Frame行の挿入は「ファイル確定後にまとめて1トランザクション」**: 各ファイルは
  `store.commit()`で個別に原子的確定するが、DB行の挿入は全ファイル確定後に
  1回のトランザクションでまとめて行う。クラッシュ時に「DB行はあるがファイルが無い」
  状態にはならない(逆に「ファイルはあるがDB行が無い」孤児は起こり得るが、
  `derived/`配下なら無害な再生成可能ゴミ)。
- **`probe()`に`has_alpha`相当の情報は含めていない**: video.pyの`_detect_alpha()`は
  内部利用のみで、契約に無い`has_alpha`キーをprobe()の戻り値に追加していない。
  代わりに`importers.py`側でPillow経由の`mode`/`transparency`チェックで別途判定する
  方式に統一した。
- **レイヤー作成時の hold 計算**: `POST /api/comps/{id}/layers`は、asset の
  `tb_num`/`tb_den`が無い(静止画)場合は`static_hold_ticks`による単一露出、
  ある場合は実測PTS差分をticks化してholdにする。最終フレームのholdは
  `last_hold_ticks`(未指定なら直前フレームとの間隔を流用)。この計算ロジックは
  `core/timeline.py`の契約に無い追加関数のため、`core/timeline.py`本体ではなく
  `web/routes_edit.py`内のヘルパーとして実装した(契約モジュールに勝手に関数を
  追加しないため)。
- **Undo/Redoはコマンドパターン、粒度は「レイヤーのexposures配列全体」**:
  hold/dx/dy/flip/matte_modeの単一フィールド編集も、タイムラインの並べ替えも、
  すべて「編集前後のexposures配列をスナップショットし、PUT /api/layers/{id}/exposures
  で戻す」という同じ仕組みに統一した。個別のPATCHより粗いが、実装が単純になり
  かつ確実に正しく戻せる。
- **画像差し替え(`POST /api/exposures/{id}/replace`)はUndo対象外**: 新しいAssetを
  作る一方向の操作で、PATCH /api/exposures/{id}には`asset_id`/`frame_id`を戻す
  手段が無いため、Undoスタックに載せない設計にした(`web/static/js/history.js`に
  明記)。
- **自動保存はタイマーを作らず、「編集APIが同期的に即時DB書き込みする」ことで
  代替**: 各PATCH/PUT/POSTがそのままSQLiteへコミットされるため、追加の自動保存
  機構(定期PUT等)は不要と判断した。ブラウザリロード後の状態復元は
  `localStorage`の`sss_last_comp_id`(直近に開いたComposition ID、あくまで
  「便利機能」でありデータの真実はDB)＋`GET /api/comps/{id}`で行う。
- **実装中に見つけた実バグ**: `canvasview.js`の初回描画時、画像が非同期読み込み
  中(Image.complete=false)だとその時点の描画がスキップされ、その後の再描画
  トリガーが無いため一時停止中は黒いままになる問題があった。`Image`の`load`
  イベントで直前の`comp`/`t`を使って再描画する処理を追加して修正した。
- **`compositions`一覧APIは§4に無い**: 直近に開いたCompositionをlocalStorageで
  覚えておく以外に一覧する手段が無い。複数Compositionを管理するUIはM1の範囲外
  とし、一覧APIの追加はM2以降で検討する。
- **HTTPテストは標準ライブラリのみで実施**: この環境にrequests/httpxが無いため、
  `urllib.request`で手作りのmultipart送信を行うテストスクリプトを一時的に作り、
  検証後に削除した(`tools/`配下には残していない。恒久化する場合は要検討)。

### M1 完了確認 (2026-09-12)

`python -m tools.doctor/make_dummy/selftest_time/selftest_parity/selftest_roundtrip/
selftest_import` を通しで実行し全PASS(`selftest_time`は実動画でのPTS変換検証を
含む)。ブラウザで: Composition新規作成→Asset選択→レイヤー追加→タイムライン
表示→再生(ループ確認)→hold編集→Undo→Redo→ドラッグ&ドロップ並べ替え→Undo→
ページリロードで状態復元、を一通り確認し、各段階でDBの実データとも一致することを
直接クエリで検証済み。APIキー未設定でも②(素材編集)が起動・動作することを確認
(generated APIクライアント import_video 等は遅延import不要、そもそも②の経路は
core/ark.py, core/gptimage.pyを一切importしていない)。

## フロントエンド再設計（案A・ライトモード / 2026-09-12）

Claude Design で3方向（A:レスポンシブ4分割改善版 / B:ステップウィザード /
C:プロツール風ドッキング）を比較し、ユーザーが **案A + ライトモード** を選択。
確定デザインは design-canvas の Artifact（「確定デザイン」ページ）が参照元。
検討時の3案はダークモードのまま「検討案」ページに保存してある。

- **配色はコントラストを数値計算して決めた**。当初案の `--accent: oklch(0.64 0.17 55)`
  は白文字を載せると 3.55:1 で WCAG AA (4.5:1) 未達だったため、oklch→sRGB→相対輝度を
  計算して以下に確定した（いずれも実測値）:
  - `--accent: oklch(0.55 0.16 55)` … 白文字 4.95:1 / 本文色として bg-1 上 4.68:1
  - `--text-2: oklch(0.52 0.012 250)` … bg-1 上 5.04:1（当初 0.58 は 3.92:1 で未達）
  - `--accent-2: oklch(0.44 0.13 210)` … bg-1 上 6.27:1 / addバッジ上 4.86:1
- **画面外はみ出しの解消方針**: 固定px指定を `clamp()` に置換し、`html,body{overflow:hidden}`
  ＋各領域に個別の `overflow:auto` ＋ グリッド子要素に `min-width:0`。
  1100px以下では左右パネルを**オーバーレイのドロワー**に切り替え、キャンバスを潰さない。
  実測でレイアウト幅 310px / 700px / 1000px / 1280px / 1440px すべて横溢れ 0px。
- **キャンバスは実寸で描き、表示サイズだけ親に収める**（`CanvasView.fit()`＋ResizeObserver）。
  1024px などの大きな Composition でも画面外に出ない。
- **操作ステップ表示は実状態から算出する**（飾りではない）: 取込=Assetがあるか、
  レイヤー=レイヤーがあるか、タイムライン=現在地。M2 未実装の「透過・合成」「出力」は
  `todo` として「予定」バッジ付きで明示し、押せる操作に見せない。
- **①素材づくり画面は見た目のみのプレースホルダー**（M3待ち）。冒頭に「この画面はまだ
  動きません」を明示し、フォーム類は `disabled`。②へのリンクだけ機能する。
- **ルーティングはハッシュ方式** (`#/`, `#/make`, `#/edit/<comp_id>`)。
  StaticFiles は `/` しか返さないためサーバー変更が不要で、かつURLから編集を再開できる。
  実装中に `history.replaceState` が `hashchange` を発火しない実バグを踏んだため、
  `ensureComp()` 内で `applyRoute()` を明示的に呼ぶようにした。
- **`[hidden]{display:none !important}` を明示的に置いた**。`.modal-backdrop{display:flex}`
  のような著者スタイルは `hidden` 属性の UA スタイルに勝ってしまい、モーダルが初期表示
  される実バグを踏んだため。
- **タイムラインは線形時間スケール固定**（既定 0.4 px/ms、ズーム±）。最小幅でクランプすると
  再生ヘッド位置とコマ位置がずれるため、クランプせずズームで対応する。
- **取り込みは3種をモーダルに集約**（単一ファイル/連番/シート）。左パネルに小さなフォームを
  3つ積むのが「窮屈で見にくい」原因だったため、パネルには ＋ ボタンだけを置いた。
- **Composition一覧APIが §4 に無い**ため、ヘッダのセレクタとホームの「再開」は
  localStorage に覚えた直近12件（id/name/時刻）から出す。データの真実はDB側。
- 画像差し替えは引き続き Undo 対象外、レイヤー追加/削除は履歴をクリアする
  （履歴の整合を保つため。M1の判断を踏襲）。

### レイアウト調整（ユーザー指摘を受けた修正 / 2026-09-12）

「中央プレビューの余白が広すぎて、右のパラメーターが表示されにくい」という指摘に対し、
配分の見直しと、その過程で見つかった実バグ3件を修正した。

- **左右パネルを広げ、中央から幅を回した**。CSS変数化して1か所で管理する:
  `--panel-left-w: clamp(200px,15vw,300px)`（旧 17vw/最大272px）
  `--panel-right-w: clamp(268px,21vw,400px)`（旧 19vw/最大300px）
  1920px幅で右パネルは 300px → 400px になり、中央の左右余白は 329px → 268px に減る。
- **実バグ1: リサイズ後にキャンバスが再フィットされず小さいまま残る**。
  ResizeObserver がリサイズ途中のサイズで測っていた。次フレーム(`requestAnimationFrame`)
  で測るようにし、さらに `render()` から毎回 `fit()` を呼ぶ(同条件なら即returnする
  キー比較付き)。1920×1000 で 575px → 696px と、縦を使い切るようになった。
- **実バグ2: 画面が低いとき中段(キャンバス)が高さ0に潰れる**。
  タイムライン行が `clamp(150px,22vh,240px)` の固定値だったため、
  `header 56px + timeline 150px > 画面高` で `1fr` が 0 になっていた。
  `grid-template-rows: 56px minmax(120px,1fr) minmax(96px,clamp(150px,22vh,240px))`
  に変更し、中段に最低120pxを確保してタイムライン側を縮めるようにした。
- **実バグ3: インスペクタのラベルがコントロールを押し出して切り取られる**。
  `flex + justify-content:space-between` ではラベルが伸びてコントロールが
  パネル外に出ていた。`grid-template-columns: minmax(0,max-content) minmax(96px,140px)`
  に変更し、さらに**パネル幅340px以下ではコンテナクエリでラベルを上に積む**
  （`@container (max-width:340px)`）。狭いドロワー(238px)でもラベル省略が
  完全に無くなり、入力欄は全幅194pxになる。
- **ヘッダーが縮めなくなるのを防ぐ**: `.app` の単一列を `minmax(0,1fr)` で固定し
  （`auto` だと子の min-content 幅で列自体が広がり、右パネルが画面外に押し出される）、
  `.app-header{overflow:hidden}` と、1480px以下でUndo/Redoの文字ラベルを畳む指定を追加。
- **狭いコマの数字を隠す**: 124コマの素材では既定ズームで1コマ約17pxになり「42」の
  数字が重なって読めなかった。`hold_ticks * scale >= 34` のときだけ数字を出す。
- キャンバスの拡大上限を 3倍 → 8倍、余白を 40px → 28px にして、小さい素材でも
  ステージを埋めるようにした。

検証: レイアウト幅 310 / 700 / 1160 / 1380 / 1600 / 1920px で横溢れ0px・
インスペクタの切り取り0件・ラベル省略0件を実測。編集/Undo/Redo/並べ替え/
ズーム/背景切替も再確認済み。


## タイムライン編集拡張（ユーザー要望 / 2026-09-13）

ユーザー要望: ①レイヤー追加時にコマの抽出方法を選びたい ②タイムラインのコマ選択で
プレビューもそのコマにしたい ③コマのダブルクリックで複製・削除（複数選択）・編集
（移動/拡大縮小）・透過処理（API）を選びたい。追加でキー操作・オニオンスキン・
表示時間の一括設定・反転/往復も採用。以下は仕様書（プラン）からの逸脱・追加を含む判断。

### 仕様書からの逸脱（ユーザー承認済み）
- **exposures.scale 列を追加（schema_version 1 → 2）**。倍率は画像中心基準、dx/dy は
  倍率1のときの左上位置（倍率1なら従来と同じ表示）。範囲 0.05〜8。
  `core/db.py` の `_migrate_v1_to_v2` だけを明示移行として許可し、移行前に
  `data/studio.v1.bak` を作る。それ以外の版不一致は従来どおり起動を止める。
  **M2 の出力（composite/sheet/pkgio・manifest）で scale を必ず適用すること**
  （現状 core/composite.py は dx/dy のみ。manifest の exposures にも scale を足す）。
- `POST /api/comps/{id}/layers` に `frame_indices` / `hold_mode`(source|fixed) /
  `fixed_hold_ticks` を追加（任意項目。未指定なら従来と同じ全フレーム）。
  source は各コマを「次に採用したコマの開始」まで、最後のコマを範囲の終端まで伸ばすので、
  間引いても範囲全体の尺が保たれる。
- `GET /api/assets/{id}/frame_scores`（§4 に無い）: 直前フレームとの平均絶対差(0-1)を
  返す（`core/keyframes.py`、numpy/Pillow のみ）。しきい値判定はフロントで即時に行う。
  `GET /api/assets` の要素に `tb_num`/`tb_den` を追加（ウィザードの尺見積もり用）。

### 透過処理 API
- §4 の `POST /api/comps/{id}/matte` を受け口として実装。対象の検証（他 Comp のコマは 400）
  まで行い、プロバイダー未登録なら **501 `matte_provider_not_configured`** を返す。
  `GET /api/matte/providers` は現在 `[]`。
- どの API を使うかは未定（ユーザー判断）。`core/matte_api.py` の `Provider` を実装して
  `register()` すれば差し替えられる。反映手順（新規 Asset 保存 → exposure 差し替え →
  `matte_mode="skip"`）は同ファイルの docstring に記載。

### フロントエンドの設計
- 複数選択は1レイヤー内に限定（`State.selectedIds` + 主選択 + anchor）。
- タイムラインは選択のたびに DOM を作り直すため、`dblclick` は取りこぼす。
  **`click` の `event.detail >= 2` でメニューを開く**（右クリックでも開く）。
- 削除モード中はコマの `draggable=false`（並べ替えのドラッグとなぞり選択が衝突するため）。
  なぞっている間は DOM のクラスだけ更新し、mouseup で1回だけ State に反映。
- 複製・削除・反転・往復・一括表示時間・編集確定・並べ替えはすべて
  `commitExposures()`（PUT /exposures 1回 = Undo 1回）に集約。
- 編集モードは下書きを `CanvasView.setOverride()` で描くだけで、確定時にだけ DB に書く。
  適用範囲（このコマ/選択中/レイヤー全体）は、移動は差分・倍率は変更時のみ同値を入れる。
- レイヤー追加自体は従来どおり Undo 対象外（History.clear）。

検証: `tools/selftest_edit_ext.py`（移行・スコア・尺保持・fixed・scale往復/範囲外422・
matte 501/400）と既存 selftest 全 PASS。ブラウザで cp_dummy を使い、コマ選択→プレビュー
（フレームごとのキャンバス色で確認）、Ctrl/Shift 選択、メニュー、複製/反転/往復/削除モード
（なぞり・Ctrl切替）/一括表示時間/透過 501 表示/編集モード（ドラッグ移動・倍率・確定・Undo）、
←/→/Home、レイヤー追加ウィザード各方式を確認。

### 追加調整（同日）
- プレビューの再生速度（x0.1〜x2、Player.setRate。表示のみで書き出しに影響しない。localStorage に記憶）。
- 編集モード: オニオンスキンの切替を「透明度」スライダーに変更。上げると編集中のコマが透け、後ろに前のコマが見える（表示のみ・保存しない）。
- 編集モード中もコマ送り（パネルの前/次ボタン、ステージの左右ボタン、キー , と .）。コマ送り中の変更は TransformEdit の base に積み、確定で PUT 1回（Undo 1回）。矢印キーは編集中は位置の微調整のまま。
- ウィザードの③を「再生の速さ」に言い換え、選択に応じた具体的な説明文と、再生時間（秒）・平均コマ/秒を表示。最後のコマの長さは折りたたみに移動。
- **罠: ブラウザが古い js をキャッシュしたまま新しい index.html を読むと、インラインスクリプトが未定義関数で止まり画面が動かない。** index.html の script src に ?v=日付 を付けた。js を変えたら v を上げること。

## Hugging Face Spaces デプロイ（ユーザー要望 / 2026-09-13）

GitHub にプッシュ後、無料でWeb上に公開したいとの要望。
`https://github.com/RMongami8/splite-animation-edit`

- 当初 Docker SDK 向けに Dockerfile を用意したが、**未認証アカウントは Docker SDK が
  ロックされている（Paid 表示）**ことが判明。カード登録なしの前提と矛盾するため、
  **Gradio SDK を使い、Gradio自体は使わず app.py で直接 FastAPI を起動する**方式に変更。
  Dockerfile は認証済みアカウント/他ホスティング用に残す。
- `app.py` は `SPACE_ID` 環境変数(Spacesコンテナに常に存在)を見て
  host/port を自動判定する(Spaces: 0.0.0.0:7860 / ローカル: 127.0.0.1:8420、
  run.bat からの起動は無変更で動く)。ユーザーがSpace側で環境変数を設定する必要はない。
- README.md の先頭に HF Spaces 用 YAML frontmatter(`sdk: gradio`,
  `python_version: "3.11"`)を付けた。3.11を明示するのは、コードが
  `str | None` 等PEP604構文(3.10+)を使うため。
- ログイン機能が無い(公開すると誰でも閲覧・編集・削除できる)ことと、無料枠は
  再起動でデータが消えうることをユーザーに確認済み。ユーザーの選択:
  「このまま公開する」(パスワード無し)。
- HFのSpace作成画面に「GitHubからインポート」欄が見当たらなかったため、
  Space作成後は `git push <space-remote> main` で手動同期する運用とした
  (HFのgit認証はユーザー自身の端末で入力してもらう。トークンを代行入力しない)。

## Render への切り替え（ユーザー要望 / 2026-09-13、続き）

Hugging Face Spaces のこのアカウントでは、Docker SDK が要認証(Paid表示)、
Gradio SDK の無料枠はZeroGPU専用(CPU basicはPRO会員のみ)と判明。
`@spaces.GPU` ダミー関数で回避する案とRenderへ切替える案を提示し、
ユーザーは **Render.com への切替**を選択。

- `app.py` のクラウド判定を一般化: `$PORT` が環境変数にあれば(Render/Heroku等の
  慣習)、または `$SPACE_ID` があれば「クラウド上」とみなし `0.0.0.0` で待受け、
  ポートは `$PORT`(無ければ HF の既定7860)を使う。ローカル(run.bat)は
  どちらも無いので従来どおり `127.0.0.1:8420`。
- 既存の Dockerfile(HF Spaces向けに用意)はそのまま Render でも使う
  (Render は Environment=Docker を選ぶとリポジトリ直下の Dockerfile を自動使用)。
- HF Space(`RyoMon1999/splite-animation-edit`)は ZeroGPU のまま起動エラーの状態で
  放置(ユーザー判断で削除するかは未定)。`git remote`の`space`は使わなくなったが
  残しても無害なため削除はしていない。
- README.md からHF Spaces frontmatterを削除し、Renderの手順に置き換えた。
