"""Сохранение манифеста идёт через каноническую модель (спека 018, US1).

WebUI не должен проверять и писать описание дома второй моделью: именно так
появляется расхождение между тем, что сохранили, и тем, что исполняется.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from core.models.manifest import Manifest
from core.persistence.manifest_store import ManifestStore
from webui.routes.manifest import put_manifest


def _payload() -> dict[str, Any]:
    """Минимальный корректный манифест.

    Returns:
        Словарь для PUT.
    """
    return {
        "instance": {"id": "probe", "name": "Probe", "owner": "probe", "created_at": ""},
        "version": 1,
        "rooms": [],
        "extensions": {"probe": {"saved_by": "test"}},
    }


class _Request:
    """Запрос с хранилищем и без работающего контейнера."""

    def __init__(self, store: ManifestStore, payload: dict[str, Any]) -> None:
        self.app = SimpleNamespace(
            state=SimpleNamespace(manifest_store=store, container=None, lifecycle_service=None)
        )
        self._payload = payload

    async def json(self) -> dict[str, Any]:
        """Тело запроса.

        Returns:
            Манифест.
        """
        return self._payload


def test_store_uses_canonical_model_by_default(tmp_path: Path) -> None:
    """Хранилище по умолчанию проверяет канонической моделью."""
    store = ManifestStore(str(tmp_path / "manifest.yaml"))

    assert store.model_type is Manifest


@pytest.mark.asyncio
async def test_put_manifest_saves_through_canonical_model(tmp_path: Path) -> None:
    """PUT сохраняет документ, который принимает та же модель, что и рантайм."""
    path = tmp_path / "manifest.yaml"
    path.write_text(
        "instance: {id: probe, name: Probe, owner: probe, created_at: ''}\nversion: 1\nrooms: []\n",
        encoding="utf-8",
    )
    store = ManifestStore(str(path))
    store.load()

    response = await put_manifest(_Request(store, _payload()))

    assert response.status_code == 200
    saved = store.current
    assert isinstance(saved, Manifest), "хранилище сохранило не каноническую модель"
    assert saved.extensions == {"probe": {"saved_by": "test"}}
