"""Состояние устройства на карточке: фактическое, а не только автомата.

Пункт 2 плана работы над веб-интерфейсом: «я как пользователь хочу видеть
состояние устройства».

Уточнение к прежней оценке
---------------------------
Состояние **автомата** на главной странице уже выводится: функция
`renderDeviceStates` в `index.html` дорисовывает бейджи состояний автоматов на
карточку устройства (FR-028). Мой прежний вывод «состояние не выводится» был
неверен — я искал обращение к `device.state` и не нашёл, хотя состояние
приходит из другого источника.

Чего действительно нет
----------------------
Фактического состояния устройства и его доступности. `/api/fsm/state` отдаёт
только состояние автомата (`OFF`, `ON_MOTION`, `IDLE`) — то есть как ведёт себя
автоматика. Состояние самого устройства (`on`/`off`) лежит в `/api/v1/devices` в
поле `state`, рядом с `status`, и в интерфейсе не отображалось нигде.

Различие существенно и практично: «автоматика в режиме ON_MOTION» ничего не
говорит о том, горит ли сейчас лампа, а «устройство недоступно» невозможно
увидеть вообще — молчащий интерфейс выглядит как «работает штатно».

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


INDEX = Path(__file__).resolve().parent.parent.parent / "src" / "webui" / "templates" / "index.html"

ADMIN = {"X-User-ID": "admin_user", "X-Is-Admin": "true"}


@pytest.fixture
def template() -> str:
    return INDEX.read_text(encoding="utf-8")


def _body(source: str, name: str, length: int = 2500) -> str:
    """Вырезать тело функции.

    Отдельная функция нужна, потому что проверка «строка встречается в файле»
    ничего не говорит о том, вызывается ли она: инъекция «убрать вызов»
    проходила незамеченной.
    """
    start = source.index(f"function {name}(")
    return source[start : start + length]


class TestDeviceStateIsFetched:
    """Состояние устройства нужно получить; автоматического его взять неоткуда."""

    def test_page_requests_device_list(self, template: str) -> None:
        """Страница запрашивает список устройств."""
        assert "/api/v1/devices" in template, (
            "состояние устройства лежит в /api/v1/devices, а страница его не "
            "запрашивает: видно только состояние автомата"
        )

    def test_page_reads_state_and_status(self, template: str) -> None:
        """Из ответа берутся и состояние, и доступность."""
        assert ".state" in template, "поле состояния устройства не читается"
        assert ".status" in template, (
            "статус доступности устройства не читается: молчащий интерфейс выглядит как работающий"
        )


class TestDeviceStateIsRendered:
    """Состояние должно попасть на карточку устройства."""

    def test_badge_element_exists_in_card(self, template: str) -> None:
        """На карточке есть место под состояние устройства."""
        assert "device-state" in template, "на карточке устройства нет элемента состояния"

    def test_state_is_keyed_by_entity(self, template: str) -> None:
        """Состояние привязывается к устройству по entity_id.

        Карточки рендерятся из манифеста и помечены `data-device`, поэтому
        сопоставление обязано идти по нему же, иначе состояния не попадут на
        карточки.
        """
        assert "data-device" in template, "карточки не помечены идентификатором устройства"
        assert "CSS.escape" in template, (
            "обращение к карточке идёт без экранирования идентификатора: "
            "идентификаторы вида light.kitchen ломают выбор элемента"
        )

    def test_automaton_state_is_still_shown(self, template: str) -> None:
        """Состояние автомата не вытесняется состоянием устройства.

        Оба нужны: автомат объясняет поведение, устройство — факт. Замена одного
        другим потеряла бы половину картины.
        """
        assert "renderDeviceStates" in template, (
            "отрисовка состояний автоматов исчезла: состояние устройства не "
            "заменяет объяснение, почему автомат в этом состоянии"
        )


class TestDeviceStateApiContract:
    """Интерфейс опирается на контракт — проверяется отдельно."""

    def test_device_payload_carries_state_and_status(self) -> None:
        """Устройство отдаёт состояние и статус."""
        from core.models.device import Device

        device = Device(
            ha_entity_id="light.probe",
            source_id="00000000-0000-0000-0000-000000000001",
            name="Проба",
            device_type="light",
            state={"state": "on"},
            status="available",
        )

        assert device.state == {"state": "on"}
        assert device.status == "available"

    def test_states_endpoint_returns_views(self) -> None:
        """Раздел состояний отдаёт представления с идентификатором устройства."""
        from main import app

        client = TestClient(app, headers=ADMIN)
        response = client.get("/api/fsm/state")

        assert response.status_code == 200
        body = response.json()
        assert "states" in body and "count" in body
        for view in body["states"]:
            assert "device_id" in view, (
                "в представлении нет device_id: состояние автомата невозможно "
                "привязать к карточке устройства"
            )


class TestRenderingIsActuallyWired:
    """Функции могут существовать и при этом не вызываться.

    Две инъекции — убрать вызов `renderDeviceState` и убрать вызов
    `renderDeviceStates` — прошли при 7 зелёных тестах: проверки искали строки в
    файле, а не вызовы в пути отрисовки.
    """

    def test_render_all_draws_automaton_states(self, template: str) -> None:
        """Общая отрисовка вызывает отрисовку состояний автоматов."""
        body = _body(template, "renderAllDevices")
        assert "renderDeviceStates(" in body, (
            "состояния автоматов не рисуются при общей отрисовке: функция есть, но не вызывается"
        )

    def test_render_all_draws_device_state(self, template: str) -> None:
        """Общая отрисовка вызывает отрисовку состояния устройства."""
        body = _body(template, "renderAllDevices")
        assert "renderDeviceState(" in body, (
            "состояние устройства не рисуется при общей отрисовке: функция есть, "
            "но не вызывается, и пользователь ничего не увидит"
        )

    def test_initial_load_fills_device_states(self, template: str) -> None:
        """Начальная загрузка наполняет состояния устройств.

        Иначе карточки получат пустые данные: функция отрисовки отработает до
        того, как пришёл ответ.
        """
        body = _body(template, "loadInitialData")
        assert "deviceStates" in body, (
            "начальная загрузка не наполняет состояния устройств: карточки "
            "останутся без состояния до первого обновления"
        )

    def test_escaping_helper_exists(self, template: str) -> None:
        """Экранирование вставляемого текста объявлено в этом же файле.

        Состояние приходит из Home Assistant и подставляется через `innerHTML`.
        Без экранирования значение извне стало бы разметкой; функция из другого
        шаблона здесь недоступна, и я на этом уже споткнулся.
        """
        assert "function escapeHtml(" in template, (
            "в index.html нет escapeHtml: подстановка состояния через innerHTML "
            "небезопасна, а функция из discovery.html здесь не объявлена"
        )

    def test_device_state_uses_escaping_helper(self, template: str) -> None:
        """Значения состояния проходят через экранирование."""
        body = _body(template, "renderDeviceState")
        # Проверяется именно подстановка названия состояния: escapeHtml в теле
        # функции есть и для статуса, поэтому проверка «есть ли вызов» удовлетворялась
        # и при снятом экранировании у названия.
        assert "escapeHtml(deviceStateLabel(" in body, (
            "название состояния вставляется без экранирования: значение приходит "
            "из Home Assistant и может содержать разметку"
        )
