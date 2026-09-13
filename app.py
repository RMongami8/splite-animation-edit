"""uvicorn エントリのみ。ロジックは web/server.py に置く（プラン §3 の規則通り）。

HOST/PORT は環境変数で上書きできる（Docker/Render/Hugging Face Spaces 等のホスティング
先が $PORT を指定してくるため）。run.bat からのローカル起動では環境変数を設定しない
ので、既定値(127.0.0.1:8420)のまま従来どおり動く。
"""
import os

import uvicorn

if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8420"))
    uvicorn.run("web.server:app", host=host, port=port, reload=False)
