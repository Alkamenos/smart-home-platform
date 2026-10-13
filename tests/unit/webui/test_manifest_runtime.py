"""Применение манифеста к рантайму (спека 017, US5, FR-027).

Проверяется то, ради чего сервис заведён: после сохранения манифеста платформа
перечитывает его без перезапуска — состав автоматов приводится к новому
манифесту, а карта маршрутизации перестраивается.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from webui.services.manifest_runtime import apply_manifest_to_runtime


class _Store:
    """Хранилище, запоминающее перечитывание."""

    def __init__(self) -> None:
        self.reloaded_into: Any = None

    def reload_into(self, target: Any) -> None:
        """Запомнить цель перечитывания."""
        self.reloaded_into = target


class _Factory:
    """Фабрика автоматов с одним определением."""

    def __init__(self) -> None:
        self._template_cache: dict[str, Any] = {"stale": True}

    def create_from_manifest(self, manifest: Any) -> list[Any]:
        """Определения автоматов по манифесту."""
        return [SimpleNamespace(entity_id="light.a_lighting_10")]


class _FSM:
    """Движок с прежним составом автоматов."""

    def __init__(self) -> None:
        self._states = {"light.a_lighting_10": object(), "light.gone_lighting_10": object()}
        self.unregistered: list[str] = []
        self.registered: list[str] = []

    def get_all_states(self) -> dict[str, Any]:
        """Текущие состояния."""
        return dict(self._states)

    def unregister(self, entity_id: str) -> None:
        """Снять автомат."""
        self.unregistered.append(entity_id)

    def register_definition(self, definition: Any, restore_state: bool = False) -> None:
        """Завести автомат."""
        self.registered.append(definition.entity_id)


def test_apply_should_reload_and_rebuild_runtime() -> None:
    """Манифест перечитывается, лишний автомат снимается, нужный заводится."""
    manifest = SimpleNamespace(rooms=[1, 2])
    fsm = _FSM()
    factory = _Factory()
    router = SimpleNamespace(built=0)

    def build_mapping() -> None:
        router.built += 1

    router._build_mapping = build_mapping
    container = SimpleNamespace(manifest=manifest, factory=factory, fsm=fsm, event_router=router)
    store = _Store()

    apply_manifest_to_runtime(store, container, lifecycle_service=None)

    assert store.reloaded_into is manifest
    assert fsm.unregistered == ["light.gone_lighting_10"]
    assert fsm.registered == ["light.a_lighting_10"]
    assert factory._template_cache == {}
    assert router.built == 1


def test_apply_should_prefer_lifecycle_service_for_routing() -> None:
    """Перестройка маршрутизации идёт через сервис жизненного цикла, если он есть."""
    lifecycle = SimpleNamespace(rebuilt=0)

    def rebuild() -> None:
        lifecycle.rebuilt += 1

    lifecycle._rebuild_event_routing = rebuild
    router = SimpleNamespace(built=0)
    router._build_mapping = lambda: None
    container = SimpleNamespace(
        manifest=SimpleNamespace(rooms=[]),
        factory=_Factory(),
        fsm=_FSM(),
        event_router=router,
    )

    apply_manifest_to_runtime(_Store(), container, lifecycle_service=lifecycle)

    assert lifecycle.rebuilt == 1
    assert router.built == 0


def test_apply_should_be_noop_without_container() -> None:
    """Без контейнера применение ничего не делает (и не падает)."""
    apply_manifest_to_runtime(_Store(), None)
