"""Метаданные параметров для формы правки поведений (пункт 4 веб-плана).

Форма строит поля из этого эндпоинта, поэтому проверка отвечает на два вопроса:

1. Данные вообще доступны браузеру — без них форма показала бы пустые поля и
   отправляла бы значения вслепую.
2. В ответе есть ``range`` и ``effective`` — именно их форма использует, чтобы
   подсказать диапазон и не выдать инертный параметр за рабочий. Эндпоинт
   `/api/templates/{name}` берёт параметры из YAML шаблона и этих полей не
   содержит, поэтому «просто взять существующий» нельзя.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.mark.usefixtures("isolated_client")
class TestBehaviorParamsEndpoint:
    """Метаданные параметров шаблона."""

    def test_should_return_params_with_range_and_effective(
        self, isolated_client: TestClient
    ) -> None:
        """Параметры приходят с диапазоном и отметкой действенности.

        Args:
            isolated_client: HTTP-клиент от имени администратора.
        """
        response = isolated_client.get("/api/behavior-params/lighting")

        assert response.status_code == 200, response.text
        params = response.json()["params"]
        assert params, "шаблон lighting обязан описывать параметры"
        for spec in params.values():
            assert "range" in spec, f"у параметра нет диапазона: {spec}"
            assert "effective" in spec, f"у параметра нет отметки действенности: {spec}"

    def test_should_mark_inert_params(self, isolated_client: TestClient) -> None:
        """Инертный параметр помечен — иначе форма покажет его как рабочий.

        Args:
            isolated_client: HTTP-клиент от имени администратора.
        """
        response = isolated_client.get("/api/behavior-params/climate_control")

        assert response.status_code == 200, response.text
        params = response.json()["params"]
        assert params["hysteresis"]["effective"] is False
        assert params["target_temp"]["effective"] is True

    def test_should_return_404_for_unknown_template(self, isolated_client: TestClient) -> None:
        """Несуществующий шаблон отвергается, а не возвращает пустой список.

        Пустой список выглядел бы в форме как «у шаблона нет параметров», и
        пользователь стёр бы их, не поняв причину.

        Args:
            isolated_client: HTTP-клиент от имени администратора.
        """
        response = isolated_client.get("/api/behavior-params/нет_такого")

        assert response.status_code == 404, response.text
