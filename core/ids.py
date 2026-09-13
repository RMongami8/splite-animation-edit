"""ID生成。プレフィックスは DB 上のテーブルを人間が判別できるようにするためのもの。

prefix: as=asset, cp=composition, ly=layer, ex=exposure, jb=job, xp=export, at=attempt
"""
import secrets

PREFIXES = {
    "asset": "as",
    "composition": "cp",
    "layer": "ly",
    "exposure": "ex",
    "job": "jb",
    "export": "xp",
    "attempt": "at",
}


def new_id(kind: str) -> str:
    """kind は PREFIXES のキー。例: new_id("asset") -> 'as_1a2b3c4d5e6f'"""
    prefix = PREFIXES.get(kind)
    if prefix is None:
        raise ValueError(f"unknown id kind: {kind!r}")
    return f"{prefix}_{secrets.token_hex(6)}"
