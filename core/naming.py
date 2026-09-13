"""命名規則テンプレート展開。

例: expand("{project}_{layer}_{action}_{i:03d}", project="p", layer="char",
           action="walk", i=3) -> "p_char_walk_003"
未知トークンは KeyError を送出する（Python の str.format 標準動作をそのまま使う）。
"""


def expand(template: str, **kw) -> str:
    try:
        return template.format(**kw)
    except KeyError as e:
        raise KeyError(f"naming template has unknown token: {e}") from e
