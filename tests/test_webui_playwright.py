"""Playwright E2E-тесты Web UI.

Запускать ОТДЕЛЬНО от основного прогона (файл исключён из addopts в pyproject.toml):

    pytest tests/test_webui_playwright.py

Почему отдельно: session-фикстура pytest-playwright использует sync API, который
внутри держит запущенный event loop. Пока она активна, любые async-тесты в том же
процессе падают с "Runner.run() cannot be called from a running event loop"
(Known Issue #13).

Особенности, зафиксированные при починке Q6:
- uvicorn запускается на фабрике ``tests.e2e_app:create_e2e_app`` (в
  ``src/webui/app.py`` нет модуль-левел ``app``, поэтому цель ``src.webui.app:app``
  падала с "Attribute 'app' not found", и все тесты получали ERR_CONNECTION_TIMED_OUT);
- приложение работает на временной копии манифеста, а его CWD — во временном
  каталоге, поэтому тесты сохранения (/devices/save, /save) не трогают репозиторий;
- страница index.html держит открытым WebSocket канала устройств
  ``/api/v1/ws/devices``, поэтому
  ``wait_for_load_state("networkidle")`` никогда не срабатывает — используются
  ``wait_until="load"`` и автоожидающие проверки ``expect(...)``;
- JSON-эндпоинты проверяются через ``page.request``: ``page.content()`` для JSON
  ответа возвращает HTML-обёртку с ``<pre>``, а не сам JSON.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect


SERVER_HOST = "127.0.0.1"
# Порт намеренно не 8125: на 8125 поднят боевой контейнер платформы, и станок,
# переиспользовавший его, проверял бы чужое состояние вместо своего (#73).
SERVER_PORT = 8177
SERVER_URL = f"http://{SERVER_HOST}:{SERVER_PORT}"

# Идентичность для запросов к API: устройства и источники отдаются
# авторизованному пользователю (DeviceAccessMiddleware).
E2E_USER_ID = "e2e_admin"
# Метка станка: сервер отвечает ей в /health, и только такой сервер можно
# переиспользовать вместо поднятого заново.
E2E_MARKER = "e2e-smoke-server"
SERVER_START_TIMEOUT_SEC = 30.0
DEFAULT_ACTION_TIMEOUT_MS = 10_000

# htmx-цели шаблонов: форма устройства грузится в #device-form-container,
# форма комнаты — в #edit-modal-content. По hx-target селекторы однозначны.
DEVICE_FORM_TARGET = "#device-form-container"
DEVICE_EDIT_BUTTON = f'button[hx-target="{DEVICE_FORM_TARGET}"][hx-get$="/edit"]'
DEVICE_ADD_BUTTON = f'button[hx-target="{DEVICE_FORM_TARGET}"][hx-get$="/add"]'


@pytest.fixture(scope="session")
def browser_context_args():
    """Configure browser context arguments."""
    return {
        "ignore_https_errors": True,
        "viewport": {"width": 1280, "height": 720},
    }


def _is_server_up() -> bool:
    """Проверяет, принимает ли сервер Web UI соединения.

    Returns:
        True, если порт отвечает.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex((SERVER_HOST, SERVER_PORT)) == 0


def _is_our_server() -> bool:
    """Проверяет, что на порту отвечает именно станок, а не посторонний сервер.

    Раньше проверка спрашивала только «отвечает ли порт», и этого хватало, пока
    станок был единственным, кто слушал 8125. Стоило на том же порту оказаться
    запущенному контейнеру платформы, станок молча пошёлл против него: тесты
    получали боевой манифест и боевой Home Assistant, а всё, что они проверяют,
    относилось к чужому состоянию. Наблюдалось это на `#73`: браузерная проверка
    формы пошла против контейнера, и её отказ был отказом боевой системы, а не
    станка.

    Returns:
        True, если сервер отвечает и помечен как станок.
    """
    try:
        request = urllib.request.Request(  # noqa: S310 - адрес локальный и фиксирован
            f"{SERVER_URL}/health",
            headers={"X-E2E-Probe": E2E_MARKER},
        )
        with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
            return E2E_MARKER in response.read().decode(errors="replace")
    except Exception:
        return False


@pytest.fixture(scope="session", autouse=True)
def start_webui_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Поднимает Web UI на временной копии манифеста и ждёт готовности.

    Yields:
        Базовый URL сервера.
    """
    if _is_server_up():
        assert _is_our_server(), (
            f"порт {SERVER_PORT} занят посторонним сервером — это не станок. "
            "Прогон против чужого сервера писал бы в боевое состояние. "
            "Освободите порт или запустите станок на другом"
        )
        yield SERVER_URL
        return

    project_root = Path(__file__).resolve().parent.parent
    work_dir = tmp_path_factory.mktemp("webui_e2e")
    manifest_copy = work_dir / "manifest.yaml"
    # Копируется ДЕМО-экземпляр из репозитория, а не боевой манифест: проверки
    # интерфейса не должны зависеть от состава дома. Раньше здесь копировался
    # боевой файл, и стоило убрать из него комнату (чистка 2026-10-09), как упали
    # четыре проверки редактора поведения: они добавляют устройство в kitchen,
    # которой в доме нет и быть не должно.
    source_manifest = project_root / "instances" / "leonids_house" / "manifest.yaml"
    shutil.copy(source_manifest, manifest_copy)

    env = {
        **os.environ,
        # Корень репозитория в PYTHONPATH — для импорта пакета src
        "PYTHONPATH": str(project_root),
        # Временный манифест: сохранения из UI не затрагивают репозиторий
        "E2E_MANIFEST_PATH": str(manifest_copy),
    }

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "tests.e2e_app:create_e2e_app",
            "--factory",
            "--host",
            SERVER_HOST,
            "--port",
            str(SERVER_PORT),
        ],
        # CWD во временном каталоге: относительный data_dir="data" в create_app
        # тоже остаётся изолированным от репозитория
        cwd=str(work_dir),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    deadline = time.monotonic() + SERVER_START_TIMEOUT_SEC
    while time.monotonic() < deadline:
        if _is_server_up():
            break
        if process.poll() is not None:
            pytest.fail(f"Web UI server завершился с кодом {process.returncode} до старта")
        time.sleep(0.25)
    else:
        process.kill()
        pytest.fail(f"Web UI server не поднялся за {SERVER_START_TIMEOUT_SEC:.0f}s")

    try:
        yield SERVER_URL
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def _ensure_ha_source_exists() -> str:
    """Создать источник Home Assistant, если его ещё нет.

    Вызывается только теми тестами, которые сохраняют устройство. Источник
    обязателен в форме (F1, specs/006): без него устройство не с чем
    синхронизировать, и браузер отклоняет отправку формы ещё до запроса на
    сервер (``required`` на ``source_id``).

    Источник создаётся точечно, а не на всю сессию: общее состояние для всех
    тестов файла меняет поведение поздних сценариев (дашборд, discovery) и
    делает их зависимыми от порядка прогона.

    Returns:
        Идентификатор созданного или найденного источника.
    """
    existing = _request_json("GET", "/api/v1/devices/sources")
    if isinstance(existing, list) and existing:
        return str(existing[0].get("id", ""))

    created = _request_json(
        "POST",
        "/api/v1/devices/sources",
        {
            "name": "E2E Home Assistant",
            "url": "http://homeassistant.local:8123",
            "token": "e2e-token-not-used-without-realsync",
        },
    )
    return str(created.get("id", ""))


def _request_json(method: str, path: str, payload: dict | None = None) -> dict | list:
    """Выполнить JSON-запрос к API платформы от имени администратора.

    Args:
        method: HTTP-метод.
        path: Путь относительно базового адреса.
        payload: Тело запроса для методов с телом.

    Returns:
        Разобранный ответ сервера.
    """
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(  # noqa: S310 - адрес локальный и фиксирован
        f"{SERVER_URL}{path}",
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            "X-User-ID": E2E_USER_ID,
            "X-Is-Admin": "true",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            body = response.read().decode()
    except urllib.error.HTTPError as error:
        # Тело ответа обязано попасть в сообщение: HTTP 400 без причины
        # не диагностируется, а именно его возвращает проверка параметров.
        detail = error.read().decode(errors="replace")
        raise AssertionError(f"{method} {path} -> HTTP {error.code}: {detail}") from error
    return json.loads(body) if body else {}


def _auth_headers() -> dict[str, str]:
    """Заголовки идентичности для прямых запросов к API.

    ``page.request`` не наследует заголовки страницы: это отдельный клиент,
    который ничего не знает про ``X-User-ID``. Эндпоинты с состояниями требуют
    идентичность и отвечают 401 без неё, поэтому такие проверки падали с
    «Missing X-User-ID header», а диагностировали это как «состояний нет».

    Returns:
        Заголовки запроса.
    """
    return {"X-User-ID": E2E_USER_ID, "X-Is-Admin": "true"}


def _first_fsm_id(page: Page) -> str:
    """Берёт идентификатор автомата из живых данных.

    Раньше здесь был зашит ``light.kitchen`` — устройство из старой копии
    манифеста. На боевом манифесте такого автомата нет, и проверка падала с 404,
    хотя диаграммы были исправны.

    Returns:
        Идентификатор первого автомата.
    """
    response = page.request.get(f"{SERVER_URL}/api/fsm/state", headers=_auth_headers())
    assert response.status == 200, f"/api/fsm/state -> {response.status}"
    states = response.json()["states"]
    assert states, (
        "на манифесте станка нет ни одного автомата — проверка диаграммы была бы "
        "пустой: она обязана смотреть на реальный автомат"
    )
    return str(states[0]["fsm_id"])


def _open_index(page: Page) -> None:
    """Открывает главную страницу и дожидается готовности к взаимодействию.

    htmx и Bootstrap подключаются с CDN: без явного ожидания клик может
    произойти до инициализации htmx, и форма устройства просто не загрузится.

    Args:
        page: Playwright page.
    """
    # networkidle недостижим: страница держит открытым WebSocket канала устройств.
    # `load` тоже ненадёжен: страница тянет htmx, Bootstrap и mermaid с CDN, и при
    # медленной сети событие загрузки не наступает за 30 с — падал таймаут
    # Page.goto без всякой связи с проверяемым. `domcontentloaded` достаточно:
    # нужные скрипты проверяются ожиданиями ниже явно.
    page.goto(SERVER_URL, wait_until="domcontentloaded")
    expect(page.locator(".room-card").first).to_be_visible(timeout=DEFAULT_ACTION_TIMEOUT_MS)
    page.wait_for_function(
        "() => typeof window.htmx !== 'undefined' && typeof window.bootstrap !== 'undefined'",
        timeout=DEFAULT_ACTION_TIMEOUT_MS,
    )


def _open_device_form(page: Page) -> None:
    """Открывает форму редактирования первого устройства.

    Args:
        page: Playwright page.
    """
    page.locator(DEVICE_EDIT_BUTTON).first.click()
    expect(page.locator('input[name="device_id"]')).to_be_visible(timeout=DEFAULT_ACTION_TIMEOUT_MS)


def _select_source(page: Page) -> None:
    """Выбрать источник Home Assistant в форме устройства.

    Источник обязателен (F1, specs/006): без него устройство не с чем
    синхронизировать, поэтому браузер не отправляет форму. Пока пользователь
    явно не выбрал источник, select остаётся на пустой заглушке, и клик
    «Save Device» не делает ничего.

    Args:
        page: Playwright page.
    """
    source_select = page.locator('select[name="source_id"]')
    source_select.select_option(index=1)
    expect(source_select).not_to_have_value("")


class TestWebUIBasics:
    """Test basic Web UI functionality."""

    def test_index_page_loads(self, page: Page):
        """Test that index page loads successfully."""
        _open_index(page)

        # Check page title
        expect(page).to_have_title(re.compile("Smart Home"))

        # Check for room cards
        expect(page.locator(".room-card").first).to_be_visible()

    def test_health_check_endpoint(self, page: Page):
        """Test health check endpoint."""
        # /health отдаёт JSON {"status": "ok"}; page.content() вернул бы HTML-обёртку
        response = page.request.get(f"{SERVER_URL}/health")

        assert response.status == 200
        assert response.json()["status"] == "ok"


class TestLiveUpdates:
    """Живые обновления состояний автоматов (spec 007, US3)."""

    def test_live_status_indicator_shows_connected(self, page: Page):
        """После загрузки индикатор показывает, что обновления включены."""
        _open_index(page)

        expect(page.locator("#live-status")).to_have_text(
            "Обновления в реальном времени", timeout=DEFAULT_ACTION_TIMEOUT_MS
        )

    def test_states_visible_without_waiting_for_event(self, page: Page):
        """Состояния показаны сразу при загрузке, до первого события (FR-028)."""
        _open_index(page)

        response = page.request.get(f"{SERVER_URL}/api/fsm/state", headers=_auth_headers())
        assert response.status == 200, response.text()
        states = response.json()["states"]

        if states:
            expect(page.locator(".device-fsm-states .fsm-state-value").first).to_be_visible(
                timeout=DEFAULT_ACTION_TIMEOUT_MS
            )

    def test_fsm_diagram_renders_as_diagram_not_json(self, page: Page):
        """Схема отображается как диаграмма, а не как JSON (FR-029)."""
        _open_index(page)

        fsm_id = _first_fsm_id(page)
        response = page.request.get(
            f"{SERVER_URL}/api/fsm/{fsm_id}/diagram", headers=_auth_headers()
        )
        assert response.status == 200, response.text()
        assert response.text().startswith("stateDiagram-v2")

        page.locator(".device-action", has_text="FSM").first.click()
        expect(page.locator("#fsm-diagram-container svg")).to_be_visible(
            timeout=DEFAULT_ACTION_TIMEOUT_MS
        )
        expect(page.locator("#fsm-diagram-container")).not_to_contain_text('{"diagram"')
        expect(page.locator("#fsm-diagram-container")).not_to_contain_text("Parse error")
        expect(page.locator("#fsm-diagram-container")).not_to_contain_text(
            "Could not find a suitable point"
        )

    def test_shows_current_state_in_fsm_modal(self, page: Page):
        """В окне схемы видно текущее состояние автоматов (FR-030)."""
        _open_index(page)

        page.locator(".device-action", has_text="FSM").first.click()
        expect(page.locator("#fsm-current-state")).to_be_visible(timeout=DEFAULT_ACTION_TIMEOUT_MS)
        expect(page.locator("#fsm-current-state .fsm-state-value").first).to_be_visible()

    def test_no_json_envelope_leaks_into_page(self, page: Page):
        """На странице нет служебного JSON-конверта диаграммы."""
        _open_index(page)

        expect(page.locator("body")).not_to_contain_text(
            '{"diagram"', timeout=DEFAULT_ACTION_TIMEOUT_MS
        )

    def test_ws_endpoint_is_not_exposed_anymore(self, page: Page):
        """Мёртвый канал /ws/live выведен из эксплуатации (T043)."""
        _open_index(page)

        status = page.request.get(f"{SERVER_URL}/ws/live")

        assert status.status == 404

    def test_dashboard_shows_real_states_not_hardcoded_active(self, page: Page):
        """Дашборд показывает состояния автоматов, а не вписанный «Active»."""
        page.goto(f"{SERVER_URL}/dashboard", wait_until="load")
        page.wait_for_function(
            "() => typeof window.Chart !== 'undefined'", timeout=DEFAULT_ACTION_TIMEOUT_MS
        )

        states = page.request.get(f"{SERVER_URL}/api/fsm/state", headers=_auth_headers()).json()[
            "states"
        ]
        if states:
            expect(page.locator("#deviceStatusTable")).not_to_contain_text(">Active<")
        expect(page.locator("#deviceStatusTable")).to_be_visible()


class TestDeviceManagement:
    """Test device management functionality."""

    def test_open_device_edit_form(self, page: Page):
        """Test opening device edit form."""
        _open_index(page)
        _open_device_form(page)

        # Check form elements
        expect(page.locator('input[name="device_id"]')).to_be_visible()
        expect(page.locator('select[name="device_type"]')).to_be_visible()

    def test_device_form_displays_room_selector(self, page: Page):
        """Test that device form has room selector."""
        _open_index(page)
        _open_device_form(page)

        room_select = page.locator('select[name="room_id"]')
        expect(room_select).to_be_visible()

        # Комнаты подгружаются в select (плюс пустая опция "Select room...")
        options = room_select.locator("option")
        expect(options.first).to_be_attached()
        assert options.count() > 1, "В форме устройства должен быть выбор комнаты"

    def test_change_device_room(self, page: Page):
        """Test changing device to different room."""
        _open_index(page)
        # Источник создаётся до открытия формы: список источников
        # подгружается вместе с формой, и созданный позже источник в select
        # не появится.
        _ensure_ha_source_exists()
        _open_device_form(page)
        _select_source(page)

        room_select = page.locator('select[name="room_id"]')
        current_room = room_select.input_value()

        # Select different room
        available_options = room_select.locator("option").count()
        if available_options > 2:
            room_select.select_option(index=2)

            new_room = room_select.input_value()
            assert new_room != current_room, "Room selection should change"

            # Save device
            page.locator("button:has-text('Save Device')").click()

            # Модалка закрывается после успешного сохранения
            expect(page.locator('input[name="device_id"]')).to_be_hidden(
                timeout=DEFAULT_ACTION_TIMEOUT_MS
            )

    def test_add_device_to_room(self, page: Page):
        """Test adding new device to a room."""
        _open_index(page)
        _ensure_ha_source_exists()

        page.locator(DEVICE_ADD_BUTTON).first.click()
        expect(page.locator('input[name="device_id"]')).to_be_visible(
            timeout=DEFAULT_ACTION_TIMEOUT_MS
        )

        # Fill device form
        page.locator('input[name="device_id"]').fill("test.newdevice")
        _select_source(page)
        page.locator('select[name="device_type"]').select_option("light")
        page.locator('input[name="device_name"]').fill("Test Device")

        # Add behavior
        page.locator("button:has-text('Add Behavior')").click()
        expect(page.locator(".behavior-item")).to_have_count(1)

        # Select template
        page.locator("select.behavior-template").last.select_option("lighting")

        # Set priority
        page.locator('input[name="behavior_priority_0"]').fill("10")

        # Save device
        page.locator("button:has-text('Save Device')").click()

        # Wait for modal to close
        expect(page.locator('input[name="device_id"]')).to_be_hidden(
            timeout=DEFAULT_ACTION_TIMEOUT_MS
        )

        # Verify device appears on the page
        expect(page.locator(":has-text('test.newdevice')").first).to_be_visible(
            timeout=DEFAULT_ACTION_TIMEOUT_MS
        )


class TestBehaviorManagement:
    """Test behavior configuration."""

    def test_add_behavior_to_device(self, page: Page):
        """Test adding behavior to device."""
        _open_index(page)
        _open_device_form(page)

        behaviors = page.locator(".behavior-item")
        behaviors_before = behaviors.count()

        # Add behavior
        page.locator("button:has-text('Add Behavior')").click()

        expect(behaviors).to_have_count(behaviors_before + 1)

    def test_expand_behavior_parameters(self, page: Page):
        """Test expanding behavior parameters section."""
        _open_index(page)
        _open_device_form(page)

        params_links = page.locator("a:has-text('Show Parameters')")
        if params_links.count() > 0:
            params_links.first.click()

            expect(page.locator(".params-form").first).to_be_visible()

    def test_remove_behavior_from_device(self, page: Page):
        """Test removing behavior from device."""
        _open_index(page)
        _open_device_form(page)

        behaviors_before = page.locator(".behavior-item").count()

        if behaviors_before > 1:
            page.locator("button:has-text('Remove')").last.click()

            expect(page.locator(".behavior-item")).to_have_count(behaviors_before - 1)


class TestBehaviorEditorForm:
    """Форма правки поведений в настоящем браузере (пункт 4 веб-плана).

    Форма собрана из контракта параметров и работает в браузере, поэтому проверять
    её в node недостаточно: там нет ни загрузки страницы, ни нажатия кнопки, ни
    ответа сервера. Здесь проверяется весь путь — открытие панели, поля из
    контракта, переключатель режимов и сохранение с последующей сверкой через API.

    Устройство и его параметры создаются проверкой, а не берутся из состояния
    прогона: иначе тест зависел бы от порядка и от того, что осталось от других
    тестов. Исходные параметры восстанавливаются в конце, чтобы проверка не
    оставляла за собой мусор для следующих.
    """

    ENTITY_ID = "light.behavior_editor_probe"

    def _ensure_device_with_behavior(self) -> str:
        """Создаёт устройство с поведением lighting и возвращает его id.

        Returns:
            Идентификатор устройства.
        """
        devices = _request_json("GET", f"/api/v1/devices?ha_entity_id={self.ENTITY_ID}")
        if isinstance(devices, list) and devices:
            found = str(devices[0]["id"])
            _request_json(
                "PUT",
                f"/api/v1/devices/{found}/behaviors",
                {
                    "behaviors": [{"template": "lighting", "priority": 10, "params": {}}],
                    "room_id": "kitchen",
                },
            )
            return found

        source_id = _ensure_ha_source_exists()
        applied = _request_json(
            "POST",
            "/api/v1/devices/apply",
            {
                "source_id": source_id,
                "dry_run": False,
                "selections": [
                    {
                        "device_entity_id": self.ENTITY_ID,
                        "device_type": "light",
                        "name": "Проба формы поведений",
                        "target_room": "kitchen",
                        "behavior_template": "lighting",
                    }
                ],
            },
        )
        created = [
            item
            for item in applied.get("devices", [])
            if item.get("ha_entity_id") == self.ENTITY_ID
        ]
        assert created, f"устройство не создано: {applied}"
        return str(created[0]["id"])

    def _open_editor(self, page: Page) -> None:
        """Открывает панель правки поведений устройства.

        Args:
            page: Playwright page.
        """
        _open_index(page)
        # Данные устройств приходят отдельным запросом после загрузки страницы,
        # а карточки комнат рисуются из манифеста. Без ожидания `devices` кнопка
        # «Поведения» ещё не отрисована: проверка полагалась на порядок запросов,
        # который в браузере не гарантирован. Именно этим объяснялся редкий сбой —
        # панель не открывалась, хотя предыдущий шаг отработал.
        page.wait_for_function(
            "() => Array.isArray(window.devices) && window.devices.length > 0",
            timeout=DEFAULT_ACTION_TIMEOUT_MS,
        )
        card = page.locator(f'.device-card[data-device="{self.ENTITY_ID}"]')
        expect(card).to_be_visible(timeout=DEFAULT_ACTION_TIMEOUT_MS)
        card.locator("button.behavior-open").click()
        expect(card.locator(".behavior-editor")).to_be_visible(timeout=DEFAULT_ACTION_TIMEOUT_MS)

    def test_should_show_effective_params_as_fields(self, page: Page) -> None:
        """Поля строятся из контракта, с диапазонами из него же.

        Args:
            page: Playwright page.
        """
        device_id = self._ensure_device_with_behavior()
        self._open_editor(page)

        brightness = page.locator('.behavior-editor [data-param="brightness"]')
        expect(brightness).to_be_visible(timeout=DEFAULT_ACTION_TIMEOUT_MS)
        # Диапазон из контракта попадает в подсказку браузера: без него форма
        # предлагала бы значения, которые сервер отвергнет.
        expect(brightness).to_have_attribute("min", "0")
        expect(brightness).to_have_attribute("max", "255")

        _request_json(
            "PUT",
            f"/api/v1/devices/{device_id}/behaviors",
            {"behaviors": [{"template": "lighting", "priority": 10, "params": {}}]},
        )

    def test_should_switch_to_json_mode_and_back(self, page: Page) -> None:
        """Переключатель режимов работает: JSON показывается, поле скрывается.

        Args:
            page: Playwright page.
        """
        self._ensure_device_with_behavior()
        self._open_editor(page)
        editor = page.locator(".behavior-editor")

        editor.locator('button[data-mode="json"]').click()
        expect(editor.locator(".behavior-json")).to_be_visible(timeout=DEFAULT_ACTION_TIMEOUT_MS)
        expect(editor.locator('[data-param="brightness"]')).to_be_hidden()

        editor.locator('button[data-mode="fields"]').click()
        expect(editor.locator('[data-param="brightness"]')).to_be_visible(
            timeout=DEFAULT_ACTION_TIMEOUT_MS
        )
        expect(editor.locator(".behavior-json")).to_be_hidden()

    def test_should_save_changed_params_and_report_inert_ones(self, page: Page) -> None:
        """Сохранение доходит до сервера и возвращает замечания об инертных.

        Args:
            page: Playwright page.
        """
        device_id = self._ensure_device_with_behavior()
        self._open_editor(page)
        editor = page.locator(".behavior-editor")

        editor.locator('[data-param="brightness"]').fill("200")
        editor.locator("button.behavior-save").click()
        expect(editor.locator('[data-part="status"]')).to_contain_text(
            "сохранено", timeout=DEFAULT_ACTION_TIMEOUT_MS
        )

        saved = _request_json("GET", f"/api/v1/devices?ha_entity_id={self.ENTITY_ID}")
        assert saved[0]["behaviors"][0]["params"] == {"brightness": 200}, saved[0]["behaviors"]

        # Инертный параметр должен быть назван, а не молча принят.
        _request_json(
            "PUT",
            f"/api/v1/devices/{device_id}/behaviors",
            {
                "behaviors": [
                    {
                        "template": "climate_control",
                        "priority": 10,
                        "params": {"hysteresis": 0.5},
                    }
                ],
                "room_id": "kitchen",
            },
        )
        page.reload(wait_until="domcontentloaded")
        self._open_editor(page)
        inert = page.locator('.behavior-editor [data-part="inert"]')
        expect(inert).to_contain_text("hysteresis", timeout=DEFAULT_ACTION_TIMEOUT_MS)

        _request_json(
            "PUT",
            f"/api/v1/devices/{device_id}/behaviors",
            {"behaviors": [{"template": "lighting", "priority": 10, "params": {}}]},
        )

    def test_should_show_server_rejection_in_page(self, page: Page) -> None:
        """Отвергнутое значение показывается в странице, а не теряется.

        Args:
            page: Playwright page.
        """
        self._ensure_device_with_behavior()
        self._open_editor(page)
        editor = page.locator(".behavior-editor")

        # Обходим подсказку диапазона: значение вне контракта должно отвергаться
        # сервером, даже если браузер его пропустил.
        editor.locator('[data-param="brightness"]').fill("9999")
        editor.locator("button.behavior-save").click()

        status = editor.locator('[data-part="status"]')
        expect(status).to_contain_text("слой 3", timeout=DEFAULT_ACTION_TIMEOUT_MS)

        saved = _request_json("GET", f"/api/v1/devices?ha_entity_id={self.ENTITY_ID}")
        assert saved[0]["behaviors"][0].get("params", {}) == {}, (
            "отвергнутое значение не должно было сохраниться"
        )


class TestTemplateAPI:
    """Test template API functionality."""

    def test_templates_api_returns_list(self, page: Page):
        """Test that /api/templates endpoint returns template list."""
        response = page.request.get(f"{SERVER_URL}/api/templates")

        assert response.status == 200
        payload = response.json()

        # Контракт эндпоинта: {"templates": [...], "count": N}
        assert isinstance(payload["templates"], list)
        assert payload["count"] == len(payload["templates"])
        assert payload["count"] > 0

        names = [template["name"] for template in payload["templates"]]
        assert any(name in names for name in ["lighting", "climate_control"])

    def test_template_info_api(self, page: Page):
        """Test that template info API returns correct data."""
        response = page.request.get(f"{SERVER_URL}/api/templates/lighting")

        assert response.status == 200
        template_info = response.json()

        assert "name" in template_info
        assert template_info["name"] == "lighting"


class TestHonestDataSections:
    """Разделы визуализаций показывают фактические данные (spec 007, US4)."""

    def _open_dashboard(self, page: Page) -> None:
        """Открыть дашборд и дождаться загрузки графиков.

        Args:
            page: Playwright page.
        """
        page.goto(f"{SERVER_URL}/dashboard", wait_until="load")
        page.wait_for_function(
            "() => typeof window.Chart !== 'undefined'", timeout=DEFAULT_ACTION_TIMEOUT_MS
        )

    def test_sections_report_no_data_when_journal_empty(self, page: Page):
        """Разделы отдают признак отсутствия данных, а не выдуманные значения."""
        heatmap = page.request.get(f"{SERVER_URL}/api/history/activity-heatmap").json()
        history = page.request.get(f"{SERVER_URL}/api/events/history").json()
        suggestions = page.request.get(f"{SERVER_URL}/api/ai/suggestions").json()

        for section in (heatmap, history, suggestions):
            assert "has_data" in section
        assert suggestions["suggestions"] == [] or suggestions["has_data"] is True

    def test_repeated_requests_return_same_values(self, page: Page):
        """Два одинаковых запроса дают одинаковый результат (SC-013)."""
        first = page.request.get(f"{SERVER_URL}/api/history/activity-heatmap").json()
        second = page.request.get(f"{SERVER_URL}/api/history/activity-heatmap").json()

        assert first == second

    def test_dashboard_shows_message_instead_of_empty_heatmap(self, page: Page):
        """Вместо пустой карты активности показано сообщение (FR-032)."""
        self._open_dashboard(page)
        heatmap = page.request.get(f"{SERVER_URL}/api/history/activity-heatmap").json()

        if not heatmap["has_data"]:
            expect(page.locator("canvas#heatmapChart")).to_be_visible()
            expect(page.locator("body")).to_contain_text("Данных пока нет")

    def test_dashboard_shows_message_instead_of_fake_suggestions(self, page: Page):
        """Вместо выдуманных подсказок показано сообщение (FR-035)."""
        self._open_dashboard(page)
        suggestions = page.request.get(f"{SERVER_URL}/api/ai/suggestions").json()

        if not suggestions["has_data"]:
            expect(page.locator("#suggestionsContainer")).to_contain_text("Данных пока нет")
            expect(page.locator("#suggestionsContainer")).not_to_contain_text("Reasoning:")


class TestResponsiveness:
    """Test responsive design."""

    @pytest.mark.parametrize(
        ("width", "height"),
        [(375, 667), (768, 1024), (1920, 1080)],
        ids=["mobile", "tablet", "desktop"],
    )
    def test_layout_at_viewport(self, page: Page, width: int, height: int):
        """Test layout for mobile/tablet/desktop viewports."""
        page.set_viewport_size({"width": width, "height": height})
        _open_index(page)

        # Check that room cards are visible
        expect(page.locator(".room-card").first).to_be_visible()


class TestLogsViewerKeepsReadingPlace:
    """Просмотр журнала не уводит читателя в конец списка.

    Записи приходят сверху (новые сверху), а страница перерисовывается целиком
    каждые две секунды. Прежний код после каждой перерисовки ставил
    `scrollTop = scrollHeight`, то есть уводил в **конец** списка — к самым
    старым записям. Читатель, который смотрел журнал, терял место и не мог
    прочитать то, что открыл.
    """

    @staticmethod
    def _entry(index: int, at_top: str) -> dict:
        """Подготовить запись журнала.

        Args:
            index: Порядковый номер записи.
            at_top: Отметка времени.

        Returns:
            Запись в формате ответа `/api/logs`.
        """
        return {
            "timestamp": f"2026-10-08T{at_top}",
            "level": "INFO",
            "message": f"Запись номер {index}",
        }

    def _open_logs(self, page: Page, entries: list[dict]) -> None:
        """Открыть журнал с подменённым ответом `/api/logs`.

        Args:
            page: Страница Playwright.
            entries: Записи журнала, новые сверху.
        """
        page.route(
            "**/api/logs*",
            lambda route: route.fulfill(status=200, content_type="application/json", json=entries),
        )
        page.goto(f"{SERVER_URL}/logs", wait_until="domcontentloaded")
        expect(page.locator(".log-entry").first).to_be_visible(timeout=DEFAULT_ACTION_TIMEOUT_MS)

    def test_viewer_starts_at_newest_entry(self, page: Page):
        """Свежие записи видны сразу, без прокрутки в конец списка."""
        entries = [self._entry(i, f"12:00:0{i}") for i in range(60)]

        self._open_logs(page, entries)

        scroll_top = page.evaluate("document.getElementById('logViewer').scrollTop")
        assert scroll_top == 0, (
            f"просмотр открылся не на новых записях: scrollTop={scroll_top}. "
            "Новые записи сверху, значит и читать надо сверху — конец списка "
            "это самые старые записи"
        )

    def test_reading_place_survives_new_entry(self, page: Page):
        """Новая запись сверху не меняет то, что читатель видит.

        Проверяется не число пикселей, а содержимое: запись добавилась сверху,
        поэтому список сдвигается вниз ровно на её высоту, и под глазами должна
        остаться та же строка. Иначе через две секунды читатель смотрит на
        другое сообщение и не понимает, что произошло.
        """
        entries = [self._entry(i, f"12:00:{i:02d}") for i in range(60)]
        self._open_logs(page, entries)

        page.evaluate("document.getElementById('logViewer').scrollTop = 300")
        visible = """() => {
            const viewer = document.getElementById('logViewer');
            const top = viewer.getBoundingClientRect().top;
            const entry = [...viewer.querySelectorAll('.log-entry')]
                .find(el => el.getBoundingClientRect().top >= top + 5);
            return entry ? entry.textContent.replace(/\\s+/g, ' ').trim() : null;
        }"""
        before = page.evaluate(visible)

        entries.insert(0, self._entry(999, "12:00:99"))
        page.evaluate("loadLogs()")
        page.wait_for_timeout(300)

        after = page.evaluate(visible)

        assert before is not None and after is not None, (
            "под прокруткой не оказалось ни одной записи"
        )
        assert after == before, (
            f"под глазами сменилась запись: было {before!r}, стало {after!r}. Новая "
            "запись добавляется сверху и не должна двигать то, что уже прочитано"
        )


class TestDiscoveryWizardListsDevices:
    """Мастер обнаружения показывает устройства источника.

    Страница падала с `preferred is not defined`: переменная была объявлена
    внутри `.map()`, а использовалась после него, то есть любая отрисовка
    списка устройств кончалась исключением. Ошибка ловилась как «источник
    недоступен», устройств — ноль, и при этом `/discovery-data` отдавал их
    полностью: смотреть надо было на саму страницу, а не на ответ API.

    Ответ источника подменяется: у стенда нет живого Home Assistant, и без
    подмены проверка измеряла бы не страницу, а достижимость чужого дома.
    """

    @staticmethod
    def _devices(count: int = 3) -> list[dict]:
        """Подготовить список устройств в форме ответа `/discovery-data`.

        Args:
            count: Сколько устройств вернуть.

        Returns:
            Список устройств.
        """
        return [
            {
                "entity_id": f"light.probe_{index}",
                "friendly_name": f"Проба {index}",
                "state": "off",
                "area_id": "gostinaia",
                "area_name": "Гостиная",
                "device_type": "light",
            }
            for index in range(count)
        ]

    def _open_with_devices(self, page: Page, devices: list[dict] | None = None) -> None:
        """Открыть мастер с подменённым ответом источника.

        Args:
            page: Страница Playwright.
            devices: Устройства для подмены; по умолчанию — три пробы.
        """
        source_id = _ensure_ha_source_exists()
        assert source_id, "источник не создан — проверять нечего"
        payload = {
            "source_id": source_id,
            "areas": [],
            "available_devices": self._devices() if devices is None else devices,
            "error": None,
        }
        page.route(
            "**/discovery-data*",
            lambda route: route.fulfill(status=200, content_type="application/json", json=payload),
        )
        # Список комнат тоже подменяется: страница берёт его из /api/rooms, а
        # на стенде он пуст, и проверка подстановки комнаты измеряла бы
        # содержимое чужого манифеста вместо логики страницы.
        page.route(
            "**/api/rooms",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                json={
                    "rooms": [
                        {"id": "gostinaia", "name": "Гостиная"},
                        {"id": "kitchen", "name": "Kitchen"},
                    ]
                },
            ),
        )
        page.goto(f"{SERVER_URL}/discovery?source_id={source_id}", wait_until="domcontentloaded")

    def test_devices_are_listed(self, page: Page):
        """Открытая страница показывает карточки устройств."""
        self._open_with_devices(page)

        expect(page.locator(".device-card").first).to_be_visible(timeout=DEFAULT_ACTION_TIMEOUT_MS)
        assert page.locator(".device-card").count() == 3, (
            "страница показала не все устройства из ответа источника"
        )

    def test_page_does_not_report_source_unavailable(self, page: Page):
        """Живой ответ источника не превращается в «источник недоступен»."""
        self._open_with_devices(page)
        expect(page.locator(".device-card").first).to_be_visible(timeout=DEFAULT_ACTION_TIMEOUT_MS)

        assert "Источник недоступен" not in page.inner_text("body"), (
            "страница назвала источник недоступным при успешном ответе: ошибка "
            "разбора списка выдаётся за недоступность источника"
        )

    def test_device_room_defaults_to_device_area(self, page: Page):
        """Комната устройства по умолчанию — его область в Home Assistant."""
        self._open_with_devices(page)
        select = page.locator(".device-room").first
        expect(select).to_be_attached(timeout=DEFAULT_ACTION_TIMEOUT_MS)

        options = select.locator("option")
        values = [options.nth(i).get_attribute("value") for i in range(options.count())]
        assert "gostinaia" in values, (
            f"комнаты стенда не содержат gostinaia: {values} — проверять "
            "подстановку не на чем, манифест стенда отличается от боевого"
        )
        assert select.input_value() == "gostinaia", (
            "комната по умолчанию не подставилась: у устройства область "
            f"gostinaia, а в списке {select.input_value()!r}"
        )
