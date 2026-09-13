"""uvicorn エントリのみ。ロジックは web/server.py に置く（プラン §3 の規則通り）。

HOST/PORT は環境変数で明示指定できる。未指定時は、Hugging Face Spaces のコンテナに
常に立つ SPACE_ID を見て自動判定する(Spaces上では 0.0.0.0:7860、ローカルでは
127.0.0.1:8420)。run.bat からのローカル起動はこれまでどおり無変更で動く。
"""
import os

import uvicorn

if __name__ == "__main__":
    in_space = "SPACE_ID" in os.environ
    host = os.environ.get("HOST", "0.0.0.0" if in_space else "127.0.0.1")
    port = int(os.environ.get("PORT", "7860" if in_space else "8420"))
    uvicorn.run("web.server:app", host=host, port=port, reload=False)
