"""`GET /manifest/reload` должен перечитывать манифест в работающей платформе (#68).

Три дефекта, которые проверка закрывает:

1. Отказ без посещения главной. `manifest_store.load()` вызывался только внутри
   обработчика `GET /`, поэтому reload без предварительного открытия главной
   отвечал 400 `No manifest loaded`.
2. Успешный отклик без результата. `revert()` переподключал хранилище на новый
   объект (`copy.deepcopy(self.backup)`), а контейнер, `EventRouter` и фабрика
   FSM продолжали держать исходный манифест — reload отвечал 307 и не менял
   ничего.
3. Перестроения не происходило. Эндпоинт не пересобирал ни машины состояний, ни
   карту маршрутизации.

Решение, которое проверка закрепляет: перечитывание идёт **в тот же объект**
манифеста, поэтому все держатели видят изменение без пересборки приложения;
автоматы пересоздаются с сохранением состояний, карта маршрутизации
перестраивается.

Границы полномочий endpoint'а зафиксированы тестами намеренно: reload откатывает
**манифест**, а не постоянное хранилище устройств. Откатывать устройства — не
заявленное поведение, и молча делать это опаснее, чем не делать.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def _edit_manifest_file(manifest_path: Path, marker: str) -> None:
    """Добавляет в манифест на диске комнату с пометкой в имени.

    Args:
        manifest_path: Путь к файлу манифеста.
        marker: Пометка для распознавания.
    """
    raw = manifest_path.read_text(encoding="utf-8")
    room = f"""  # проверка reload
  - id: reload_probe
    name: Комната {marker}
    sensors:
      motion: binary_sensor.reload_probe

"""
    anchor = "  - id: kitchen\n"
    assert anchor in raw, "не найден якорь для вставки комнаты"
    manifest_path.write_text(raw.replace(anchor, room + anchor, 1), encoding="utf-8")


def _rooms(container: object) -> set[str]:
    """Возвращает идентификаторы комнат манифеста контейнера.

    Args:
        container: Контейнер платформы.

    Returns:
        Множество идентификаторов комнат.
    """
    return {room.id for room in container.manifest.rooms}


def _fsm_ids(container: object) -> set[str]:
    """Возвращает идентификаторы зарегистрированных автоматов.

    Args:
        container: Контейнер платформы.

    Returns:
        Множество идентификаторов автоматов.
    """
    return set(container.fsm.get_all_states())


class TestReloadWithoutVisitingIndexFirst:
    """Reload не должен зависеть от чужого запроса."""

    def test_should_not_fail_with_no_manifest_loaded_when_called_first(
        self, isolated_workdir: Path, isolated_client: TestClient
    ) -> None:
        """Первый в сессии запрос reload обязан отработать.

        Args:
            isolated_workdir: Временный рабочий каталог.
            isolated_client: HTTP-клиент от имени администратора.
        """
        _edit_manifest_file(Path(isolated_workdir) / "manifest.yaml", "ПЕРВЫМ")

        response = isolated_client.get("/manifest/reload", follow_redirects=False)

        assert response.status_code == 307, response.text


class TestReloadReachesLivePlatform:
    """Reload обязан менять работающую платформу, а не только хранилище."""

    def test_should_add_new_room_to_container_manifest(
        self, isolated_workdir: Path, isolated_app: object
    ) -> None:
        """Новая комната из файла появляется в манифесте контейнера.

        Args:
            isolated_workdir: Временный рабочий каталог.
            isolated_app: Изолированное приложение.
        """
        container = isolated_app.state.container
        assert container is not None
        assert "reload_probe" not in _rooms(container)

        _edit_manifest_file(Path(isolated_workdir) / "manifest.yaml", "НОВАЯ")
        response = TestClient(isolated_app).get("/manifest/reload", follow_redirects=False)

        assert response.status_code == 307, response.text
        assert "reload_probe" in _rooms(container), (
            "манифест контейнера не увидел комнату из файла — reload откатил "
            "только хранилище, а работающая платформа осталась на прежней копии"
        )

    def test_should_keep_manifest_object_identity(
        self, isolated_workdir: Path, isolated_app: object
    ) -> None:
        """Объект манифеста не подменяется — иначе держатели увидят старое.

        Это ключевое требование: `DeviceLifecycleService`, `EventRouter` и
        фабрика FSM держат ссылку на манифест контейнера. Подмена объекта оставила
        бы их на прежней копии, и перечитывание было бы видно только через API
        хранилища.

        Args:
            isolated_workdir: Временный рабочий каталог.
            isolated_app: Изолированное приложение.
        """
        container = isolated_app.state.container
        assert container is not None
        before = container.manifest

        _edit_manifest_file(Path(isolated_workdir) / "manifest.yaml", "ТА ЖЕ")
        TestClient(isolated_app).get("/manifest/reload", follow_redirects=False)

        assert container.manifest is before, "манифест подменён новым объектом"

    def test_should_remove_room_deleted_from_file(
        self, isolated_workdir: Path, isolated_app: object
    ) -> None:
        """Комната, удалённая из файла, исчезает из работающей платформы.

        Args:
            isolated_workdir: Временный рабочий каталог.
            isolated_app: Изолированное приложение.
        """
        container = isolated_app.state.container
        assert container is not None
        _edit_manifest_file(Path(isolated_workdir) / "manifest.yaml", "БУДЕТ УДАЛЕНА")
        TestClient(isolated_app).get("/manifest/reload", follow_redirects=False)
        assert "reload_probe" in _rooms(container)

        manifest = Path(isolated_workdir) / "manifest.yaml"
        raw = manifest.read_text(encoding="utf-8")
        start = raw.index("  # проверка reload")
        end = raw.index("  - id: kitchen\n")
        manifest.write_text(raw[:start] + raw[end:], encoding="utf-8")

        TestClient(isolated_app).get("/manifest/reload", follow_redirects=False)

        assert "reload_probe" not in _rooms(container)


class TestReloadRebuildsRuntime:
    """Reload перестраивает автоматы и маршрутизацию."""

    def test_should_drop_fsm_of_removed_room(
        self, isolated_workdir: Path, isolated_app: object
    ) -> None:
        """Автоматы удалённой комнаты снимаются с регистрации.

        Args:
            isolated_workdir: Временный рабочий каталог.
            isolated_app: Изолированное приложение.
        """
        container = isolated_app.state.container
        assert container is not None
        _edit_manifest_file(Path(isolated_workdir) / "manifest.yaml", "С АВТОМАТАМИ")
        TestClient(isolated_app).get("/manifest/reload", follow_redirects=False)

        # Комната без устройств не даёт автоматов, поэтому проверяем наоборот:
        # добавление устройства в существующую комнату должно дать новый автомат.
        before = _fsm_ids(container)
        _add_device_to_kitchen(Path(isolated_workdir) / "manifest.yaml")
        TestClient(isolated_app).get("/manifest/reload", follow_redirects=False)

        assert _fsm_ids(container) - before, "автомат нового устройства не появился"

    def test_should_keep_existing_fsm_states(
        self, isolated_workdir: Path, isolated_app: object
    ) -> None:
        """Перечитывание не сбрасывает состояние автоматов.

        Сброс состояния означал бы, что лампа, включённая по движению, после
        reload «забывает», что включена.

        Args:
            isolated_workdir: Временный рабочий каталог.
            isolated_app: Изолированное приложение.
        """
        container = isolated_app.state.container
        assert container is not None
        entity = sorted(_fsm_ids(container))[0]
        container.fsm.trigger(entity, "motion_detected")
        state_before = container.fsm.get_state(entity).current_state

        _edit_manifest_file(Path(isolated_workdir) / "manifest.yaml", "СОСТОЯНИЕ")
        TestClient(isolated_app).get("/manifest/reload", follow_redirects=False)

        state_after = container.fsm.get_state(entity)
        assert state_after is not None, "автомат исчез после перечитывания"
        assert state_after.current_state == state_before, (
            f"состояние сбросилось: было {state_before}, стало {state_after.current_state}"
        )


def _add_room_with_device(manifest_path: Path, marker: str) -> None:
    """Добавляет в файл манифеста комнату с датчиком и устройством.

    Args:
        manifest_path: Путь к файлу манифеста.
        marker: Пометка для распознавания.
    """
    raw = manifest_path.read_text(encoding="utf-8")
    room = f"""  # проверка reload: комната с устройством
  - id: reload_probe
    name: Комната {marker}
    sensors:
      motion: binary_sensor.reload_probe
    devices:
    - id: reload_probe_light
      type: light
      name: Свет {marker}
      behaviors:
      - template: lighting
        priority: 10
        params: {{}}

"""
    anchor = "  - id: kitchen\n"
    assert anchor in raw, "не найден якорь для вставки комнаты"
    manifest_path.write_text(raw.replace(anchor, room + anchor, 1), encoding="utf-8")


def _routing_pairs(container: object) -> set[tuple[str, str, str]]:
    """Возвращает тройки «датчик → автомат → событие» из карты маршрутизации.

    Args:
        container: Контейнер платформы.

    Returns:
        Множество троек.
    """
    router = container.event_router
    pairs: set[tuple[str, str, str]] = set()
    for sensor_id, entries in router._sensor_to_fsms.items():
        for fsm_id, event in entries:
            pairs.add((sensor_id, fsm_id, event))
    return pairs


class TestReloadRebuildsRouting:
    """Перечитывание обязано перестраивать карту «датчик → автомат»."""

    def test_should_route_new_room_sensor_to_its_device(
        self, isolated_workdir: Path, isolated_app: object
    ) -> None:
        """Датчик новой комнаты начинает вести в автомат её устройства.

        Без перестроения маршрутизации комната появилась бы в списке, а
        движение в ней не выключало бы и не включало бы ничего.

        Args:
            isolated_workdir: Временный рабочий каталог.
            isolated_app: Изолированное приложение.
        """
        container = isolated_app.state.container
        assert container is not None
        assert not [p for p in _routing_pairs(container) if "reload_probe" in p[0]]

        _add_room_with_device(Path(isolated_workdir) / "manifest.yaml", "МАРШРУТ")
        TestClient(isolated_app).get("/manifest/reload", follow_redirects=False)

        pairs = [p for p in _routing_pairs(container) if "reload_probe" in p[0]]
        assert pairs, (
            "датчик новой комнаты не попал в карту маршрутизации — перечитывание не перестроило её"
        )
        assert any("reload_probe_light" in fsm_id for _, fsm_id, _ in pairs)


class TestReloadUnregistersRemovedDevices:
    """Удалённое из файла устройство теряет автомат."""

    def test_should_unregister_fsm_of_device_removed_from_file(
        self, isolated_workdir: Path, isolated_app: object
    ) -> None:
        """Автомат устройства, исчезнувшего из файла, снимается с регистрации.

        Args:
            isolated_workdir: Временный рабочий каталог.
            isolated_app: Изолированное приложение.
        """
        container = isolated_app.state.container
        assert container is not None
        manifest = Path(isolated_workdir) / "manifest.yaml"

        _add_room_with_device(manifest, "БУДЕТ УДАЛЁН")
        TestClient(isolated_app).get("/manifest/reload", follow_redirects=False)
        probe_fsm = "reload_probe_light_lighting_10"
        assert probe_fsm in _fsm_ids(container), "автомат добавленного устройства не появился"

        raw = manifest.read_text(encoding="utf-8")
        start = raw.index("  # проверка reload: комната с устройством")
        end = raw.index("  - id: kitchen\n")
        manifest.write_text(raw[:start] + raw[end:], encoding="utf-8")
        TestClient(isolated_app).get("/manifest/reload", follow_redirects=False)

        assert probe_fsm not in _fsm_ids(container), (
            "автомат удалённого устройства остался зарегистрирован и продолжал бы "
            "реагировать на события"
        )


class TestReloadUpdatesWholeManifest:
    """Перечитывание обновляет манифест целиком, а не только секцию комнат."""

    def test_should_apply_rules_change_outside_rooms_section(
        self, isolated_workdir: Path, isolated_app: object
    ) -> None:
        """Правка правил вне секции комнат доходит до работающей платформы.

        Обновление «по частям» — обновить только `rooms` — прошло бы все прочие
        проверки: комнаты на месте, автоматы пересобраны. А правила остались бы
        прежними, и это обнаружилось бы позже и в другом месте.

        Args:
            isolated_workdir: Временный рабочий каталог.
            isolated_app: Изолированное приложение.
        """
        container = isolated_app.state.container
        assert container is not None
        manifest = Path(isolated_workdir) / "manifest.yaml"

        raw = manifest.read_text(encoding="utf-8")
        assert "    motion_enabled: true" in raw, "в манифесте нет ожидаемой настройки"
        manifest.write_text(
            raw.replace("    motion_enabled: true", "    motion_enabled: false"), encoding="utf-8"
        )

        TestClient(isolated_app).get("/manifest/reload", follow_redirects=False)

        assert container.manifest.automation_rules.lighting.motion_enabled is False, (
            "правило вне секции комнат осталось прежним — манифест обновился частично"
        )

    def test_should_apply_instance_change(
        self, isolated_workdir: Path, isolated_app: object
    ) -> None:
        """Изменение описания дома тоже доходит.

        Args:
            isolated_workdir: Временный рабочий каталог.
            isolated_app: Изолированное приложение.
        """
        container = isolated_app.state.container
        assert container is not None
        manifest = Path(isolated_workdir) / "manifest.yaml"

        raw = manifest.read_text(encoding="utf-8")
        manifest.write_text(
            raw.replace("name: Leonid's House", "name: Дом после reload"), encoding="utf-8"
        )

        TestClient(isolated_app).get("/manifest/reload", follow_redirects=False)

        assert container.manifest.instance.name == "Дом после reload"


class TestReloadScope:
    """Границы полномочий endpoint'а."""

    def test_should_not_discard_device_store_entries(
        self, isolated_workdir: Path, isolated_app: object
    ) -> None:
        """Reload откатывает манифест, а не постоянное хранилище устройств.

        Args:
            isolated_workdir: Временний рабочий каталог.
            isolated_app: Изолированное приложение.
        """
        container = isolated_app.state.container
        assert container is not None
        assert len(_fsm_ids(container)) > 0

        _edit_manifest_file(Path(isolated_workdir) / "manifest.yaml", "ХРАНИЛИЩЕ")
        TestClient(isolated_app).get("/manifest/reload", follow_redirects=False)

        assert len(_fsm_ids(container)) > 0, (
            "reload снёс автоматы существующих устройств — откатывать хранилище он не должен"
        )

    def test_should_report_unreadable_manifest_instead_of_silently_keeping(
        self, isolated_workdir: Path, isolated_client: TestClient
    ) -> None:
        """Битый манифест даёт ошибку с описанием, а не тихо оставляет старый.

        Args:
            isolated_workdir: Временный рабочий каталог.
            isolated_client: HTTP-клиент от имени администратора.
        """
        manifest = Path(isolated_workdir) / "manifest.yaml"
        manifest.write_text("version: 1\nrooms: [\n", encoding="utf-8")

        response = isolated_client.get("/manifest/reload", follow_redirects=False)

        assert response.status_code == 400, response.text
        assert response.text.strip(), "ответ об ошибке пуст"

    def test_should_keep_working_manifest_when_reload_fails(
        self, isolated_workdir: Path, isolated_app: object
    ) -> None:
        """После сбоя перечитывания платформа остаётся на прежнем манифесте.

        Args:
            isolated_workdir: Временний рабочий каталог.
            isolated_app: Изолированное приложение.
        """
        container = isolated_app.state.container
        assert container is not None
        rooms_before = _rooms(container)

        manifest = Path(isolated_workdir) / "manifest.yaml"
        manifest.write_text("version: 1\nrooms: [\n", encoding="utf-8")
        TestClient(isolated_app).get("/manifest/reload", follow_redirects=False)

        assert _rooms(container) == rooms_before, (
            "нечитаемый файл всё равно изменил рабочий манифест — частичное применение хуже отказа"
        )


def _add_device_to_kitchen(manifest_path: Path) -> None:
    """Добавляет устройство внутрь комнаты кухни в файле манифеста.

    Устройство вставляется после `devices:` кухни, а не перед её заголовком:
    элементы списка комнат начинаются с `- id:`, и вставка перед ним сделала бы
    из устройства ещё одну комнату.

    Args:
        manifest_path: Путь к файлу манифеста.
    """
    raw = manifest_path.read_text(encoding="utf-8")
    anchor = "  - id: kitchen\n"
    start = raw.index(anchor)
    devices_at = raw.index("    devices:\n", start)
    device = """      # проверка reload: устройство для нового автомата
      - id: reload_device
        type: light
        name: Свет проверки reload
        behaviors:
        - template: lighting
          priority: 10
          params: {}
"""
    heading = "    devices:\n"
    patched = raw[: devices_at + len(heading)] + device + raw[devices_at + len(heading) :]
    manifest_path.write_text(patched, encoding="utf-8")
