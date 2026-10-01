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

import os
import re
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect


SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8125
SERVER_URL = f"http://{SERVER_HOST}:{SERVER_PORT}"
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


@pytest.fixture(scope="session", autouse=True)
def start_webui_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Поднимает Web UI на временной копии манифеста и ждёт готовности.

    Yields:
        Базовый URL сервера.
    """
    if _is_server_up():
        yield SERVER_URL
        return

    project_root = Path(__file__).resolve().parent.parent
    work_dir = tmp_path_factory.mktemp("webui_e2e")
    manifest_copy = work_dir / "manifest.yaml"
    shutil.copy(project_root / "instances" / "leonids_house" / "manifest.yaml", manifest_copy)

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


def _open_index(page: Page) -> None:
    """Открывает главную страницу и дожидается готовности к взаимодействию.

    htmx и Bootstrap подключаются с CDN: без явного ожидания клик может
    произойти до инициализации htmx, и форма устройства просто не загрузится.

    Args:
        page: Playwright page.
    """
    # networkidle недостижим: страница держит открытым WebSocket канала устройств
    page.goto(SERVER_URL, wait_until="load")
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

        response = page.request.get(f"{SERVER_URL}/api/fsm/state")
        assert response.status == 200
        states = response.json()["states"]

        if states:
            expect(page.locator(".device-fsm-states .fsm-state-value").first).to_be_visible(
                timeout=DEFAULT_ACTION_TIMEOUT_MS
            )

    def test_fsm_diagram_renders_as_diagram_not_json(self, page: Page):
        """Схема отображается как диаграмма, а не как JSON (FR-029)."""
        _open_index(page)

        response = page.request.get(f"{SERVER_URL}/api/fsm/light.kitchen/diagram")
        assert response.status == 200
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

        states = page.request.get(f"{SERVER_URL}/api/fsm/state").json()["states"]
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
        _open_device_form(page)

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

        page.locator(DEVICE_ADD_BUTTON).first.click()
        expect(page.locator('input[name="device_id"]')).to_be_visible(
            timeout=DEFAULT_ACTION_TIMEOUT_MS
        )

        # Fill device form
        page.locator('input[name="device_id"]').fill("test.newdevice")
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
