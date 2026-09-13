# SpriteSheet Studio

参照画像・動画からコマ送りアニメーションシート（スプライトシート）を作るための
Web ツールです。動画・連番画像・グリッドシートを取り込み、レイヤーとタイムラインで
編集し、シート/GIF/MP4 等に書き出します（書き出し機能は実装中）。

## ⚠️ 無料公開版について

このアプリにはログイン機能がありません。**URLを知っている人は誰でも、素材の
閲覧・編集・削除ができます。** 複数人が同時に開くと同じデータを取り合う形になります。
また無料ホスティングの特性上、しばらく使われないとサーバーが休止し、次回アクセス時
（あるいは再デプロイ時）に保存していたデータが失われることがあります。
**大事な素材は各自の手元にも保存してください。**

## Render (無料枠) にデプロイする

1. https://render.com にサインアップ／ログイン（カード登録不要）
2. **New +** → **Web Service** → GitHub と連携し、このリポジトリ
   (`RMongami8/splite-animation-edit`) を選択
3. 設定:
   - **Environment**: `Docker`（リポジトリ直下の `Dockerfile` を自動で使う）
   - **Instance Type**: `Free`
4. **Create Web Service** を押すとビルド・デプロイが始まる
5. 数分後、`https://<サービス名>.onrender.com` で公開される

`app.py` は Render が渡す `$PORT` を自動で読み、`0.0.0.0` で待ち受けるように
なっているので、追加の環境変数設定は不要です。無料プランは15分操作が無いと
スリープし、次のアクセス時に起動し直すまで30秒〜1分ほどかかります。

`Dockerfile` は Hugging Face Spaces (Docker SDK) など、他のホスティング先でも
そのまま使えます。

## ローカルで動かす

Windows 環境が前提です。

```bash
git clone https://github.com/RMongami8/splite-animation-edit.git
cd splite-animation-edit
run.bat
```

`run.bat` が venv を自動作成し、依存関係をインストールしてから
`http://127.0.0.1:8420` でサーバーを起動します。

生成AI機能（①素材づくり）を使う場合は `.env.example` を `.env` にコピーし、
APIキーを設定してください。②素材編集（取り込み・レイヤー編集・タイムライン）は
APIキーが無くても動作します。

## 開発メモ

- 唯一の仕様書・実装判断の記録は `docs/decisions.md` を参照してください。
- 検証用のダミー素材生成: `python -m tools.make_dummy`
- 一括セルフテスト: `python -m tools.doctor` ほか `tools/selftest_*.py`
