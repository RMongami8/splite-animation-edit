"""uvicorn エントリのみ。ロジックは web/server.py に置く（プラン §3 の規則通り）。

HOST/PORT は環境変数で明示指定できる。未指定時は、ホスティング先が付与する
$PORT(Render/Heroku等の一般的な慣習)、または Hugging Face Spaces のコンテナに
常に立つ $SPACE_ID の有無で「クラウド上か」を判定し、クラウドなら 0.0.0.0 で
待ち受ける(相手先の $PORT を使い、無ければ 7860)。どちらも無いローカル実行
(run.bat)では、これまでどおり 127.0.0.1:8420 のまま変わらない。
"""
import os

import uvicorn

if __name__ == "__main__":
    port_env = os.environ.get("PORT")
    in_space = "SPACE_ID" in os.environ
    is_cloud = in_space or port_env is not None
    host = os.environ.get("HOST", "0.0.0.0" if is_cloud else "127.0.0.1")
    port = int(port_env or ("7860" if in_space else "8420"))
    uvicorn.run("web.server:app", host=host, port=port, reload=False)
