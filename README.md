---
title: SpriteSheet Studio
emoji: 🧩
colorFrom: yellow
colorTo: red
sdk: gradio
sdk_version: 6.27.0
python_version: "3.12"
app_file: app.py
pinned: false
---

# SpriteSheet Studio

参照画像・動画からコマ送りアニメーションシート（スプライトシート）を作るための
Web ツールです。動画・連番画像・グリッドシートを取り込み、レイヤーとタイムラインで
編集し、シート/GIF/MP4 等に書き出します（書き出し機能は実装中）。

## このリポジトリを Hugging Face Spaces で動かす場合の注意

SDK は **Gradio** を選んでください（Docker SDK はアカウント未認証だと使えないため）。
中身は Gradio を使わず、このリポジトリの `app.py` がそのまま FastAPI サーバーを
起動します（Gradio Space は「Python を実行できる無料コンテナ」として使っています）。
`SPACE_ID` 環境変数が立っている（＝Spaces上で動いている）ことを `app.py` が検知して
自動的に `0.0.0.0:7860` で待ち受けるので、追加の環境変数設定は不要です。

`Dockerfile` はアカウント認証済み・または他のホスティング先（Render 等）で
Docker SDK を使いたくなったときのために残してあります。

## ⚠️ このURLで公開されている版について

このアプリにはログイン機能がありません。**URLを知っている人は誰でも、素材の
閲覧・編集・削除ができます。** 複数人が同時に開くと同じデータを取り合う形になります。
また無料ホスティングの特性上、しばらく使われないとサーバーが休止し、次回アクセス時
（あるいは再デプロイ時）に保存していたデータが失われることがあります。
**大事な素材は各自の手元にも保存してください。**

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
