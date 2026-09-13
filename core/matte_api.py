"""外部APIによる透過(背景除去)の差し替え可能な受け口。

現時点ではプロバイダーを1つも登録していない(ユーザー判断: API は後日決める)。
プロバイダーを足すときは Provider を実装して register() するだけでよい。
APIキーはプロバイダー内で読み、レスポンス・ログに出さない(CLAUDE.md 規則12)。

後日の反映手順(web/routes_matte.py から呼ぶ想定):
  1. exposure の元フレームを load_rgba で読む
  2. provider.remove_background(rgba) で透過済み RGBA を得る
  3. importers.import_image と同じ経路で新規 Asset として保存(originals/ は追記のみ)
  4. exposure の asset_id/frame_id を差し替え、matte_mode="skip"
     (replace_exposure_image と同じ。透過済みにクロマキーを掛け直さない §5)
"""
from typing import Protocol

import numpy as np


class Provider(Protocol):
    name: str

    def remove_background(self, rgba: np.ndarray) -> np.ndarray:
        """(h,w,4) uint8 ストレートアルファ -> 同寸法の透過済み RGBA。"""
        ...


_registry: dict[str, Provider] = {}


def register(provider: Provider) -> None:
    _registry[provider.name] = provider


def available_providers() -> list[str]:
    return sorted(_registry)


def get_provider(name: str | None) -> Provider | None:
    if not _registry:
        return None
    if not name or name == "auto":
        return _registry[available_providers()[0]]
    return _registry.get(name)
