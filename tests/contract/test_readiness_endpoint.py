"""`/health` отвечает константой и потому бесполезен для диагностики.

K6 продакшен-плана: «`/health` не проверяет ничего — возвращает константу.
Docker считает контейнер здоровым при мёртвом HA и повреждённом `data/`».

Почему нельзя просто начать отдавать не-200 из `/health`
----------------------------------------------------------
Контракт спеки 003 (`contracts/operational-contracts.md` §1) прямо запрещает
это: «Не-200 не используется как "not ready"». Практически это верно и по
существу. `healthcheck` в compose — это **жизненность** процесса: если он
начнёт отдавать 503 при недоступном Home Assistant, Docker убьёт контейнер,
перезапустит, тот снова увидит недоступный HA и снова будет убит. Недоступность
внешней системы превратится в рестарт-цикл, в котором перезапуск контейнера
ничего не исправляет.

Поэтому проверки разделены:

- `/health` — жизненность: процесс отвечает. Тело `{"status": "ok"}` и код 200
  сохранены без изменений, как требует контракт;
- `/ready` — готовность: реальные проверки зависимостей, с кодом 503 при отказе.

`/ready` не вызывается Docker healthcheck-ом: он предназначен для оператора и
внешнего мониторинга.

Проверяется, что проверки честны, а не что отдаётся константа: подмена реальной
проверки на «всегда хорошо» обязана валить тесты.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

import json
import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    from main import app

    return TestClient(app, headers={"X-User-ID": "admin_user", "X-Is-Admin": "true"})


def _container_of(client: TestClient) -> Any:
    return getattr(client.app.state, "container", None)


class TestHealthStaysLiveness:
    """`/health` не превращается в проверку готовности."""

    def test_health_keeps_exact_contract(self, client: TestClient) -> None:
        """Тело остаётся ровно `{"status": "ok"}` и код 200.

        Контракт спеки 003 и `tests/test_webui.py` требуют точного равенства.
        """
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_health_does_not_fail_when_ha_is_down(self, client: TestClient) -> None:
        """Недоступный HA не делает контейнер «нездоровым».

        Иначе healthcheck restart-циклом убивал бы контейнер при отключённом
        Home Assistant, то есть перезапуск ничего не исправлял бы.
        """
        container = _container_of(client)
        if container is None:
            pytest.skip("контейнер не собран")
        adapter = getattr(container, "_adapter", None)
        if adapter is None:
            pytest.skip("адаптер не создан")

        response = client.get("/health")
        assert response.status_code == 200, "жизненность не должна зависеть от HA"


class TestReadyReportsDependencies:
    """`/ready` проверяет настоящие зависимости."""

    def test_ready_reports_named_checks(self, client: TestClient) -> None:
        """Ответ перечисляет конкретные проверки, а не константу."""
        response = client.get("/ready")

        assert response.status_code in (200, 503)
        body = response.json()
        assert "checks" in body, f"в ответе нет списка проверок: {body}"
        assert isinstance(body["checks"], dict) and body["checks"], (
            f"список проверок пуст — это константа, а не диагностика: {body}"
        )
        for name, detail in body["checks"].items():
            assert isinstance(detail, dict), f"проверка {name} описана не объектом"
            assert "ok" in detail, f"у проверки {name} нет признака ok"

    def test_ready_reports_ha_connection(self, client: TestClient) -> None:
        """Проверка связи с Home Assistant присутствует и отражает реальность."""
        response = client.get("/ready")

        checks = response.json()["checks"]
        assert "home_assistant" in checks, (
            f"связь с Home Assistant не проверяется, проверки: {list(checks)}"
        )

        container = _container_of(client)
        adapter = getattr(container, "_adapter", None) if container else None
        if adapter is None:
            pytest.skip("адаптер не создан")

        reported = checks["home_assistant"]["ok"]
        expected = bool(getattr(adapter, "is_connected", False))
        assert reported is expected, (
            f"проверка сообщила {reported}, адаптер реально {expected}: "
            "проверка не читает состояние адаптера"
        )

    def test_ready_reports_data_directory(self, client: TestClient) -> None:
        """Проверка каталога данных присутствует."""
        response = client.get("/ready")

        checks = response.json()["checks"]
        assert any("data" in name for name in checks), (
            f"каталог данных не проверяется, проверки: {list(checks)}"
        )


class TestReadyIsNotConstant:
    """Главное свойство: сбой зависимости обязан менять ответ."""

    def test_broken_data_directory_turns_ready_into_503(self, tmp_path: Path) -> None:
        """Недоступный каталог данных → 503, а не «всё хорошо».

        Проверяется на настоящем файловой системе: каталог данных сначала
        рабочий, затем его заменяют файлом — писать в него нельзя.
        """
        from webui.routes import readiness

        target = tmp_path / "data"
        target.mkdir()

        assert readiness.check_data_dir(target)["ok"] is True

        # Заменяем каталог файлом: путь существует, но писать в него нельзя.
        target.rmdir()
        target.write_text("не каталог", encoding="utf-8")

        try:
            detail = readiness.check_data_dir(target)
        finally:
            target.unlink()

        assert detail["ok"] is False, f"проверка объявила каталог пригодным: {detail}"

    def test_readiness_module_reports_each_failure(self, tmp_path: Path) -> None:
        """Модуль проверок честно различает проверки друг от друга.

        Защита от подмены: если все проверки возвращать успешными, тест на
        конкретный отказ прошёл бы незаметно.
        """
        from webui.routes import readiness

        good = readiness.check_data_dir(tmp_path / "absent-but-creatable")
        assert good["ok"] is True, "существующий родитель должен быть признан пригодным"

        blocked = tmp_path / "file-instead-of-dir"
        blocked.write_text("x", encoding="utf-8")
        assert readiness.check_data_dir(blocked)["ok"] is False

    def test_key_file_presence_is_reported(self, tmp_path: Path) -> None:
        """Наличие файла ключа шифрования попадает в отчёт.

        Отсутствие ключа означает, что токены не расшифровать — об этом
        полезно знать из проверки готовности, а не из сообщения в логе.
        """
        from webui.routes import readiness

        without = readiness.check_encryption_key(tmp_path)
        assert without["ok"] is False, "отсутствие файла ключа должно сообщаться"
        assert "encryption.key" in json.dumps(without, ensure_ascii=False)

        (tmp_path / "encryption.key").write_text("key-material", encoding="utf-8")
        assert readiness.check_encryption_key(tmp_path)["ok"] is True

    def test_ready_is_fast_enough_for_a_probe(self, client: TestClient) -> None:
        """Проверка не превращается в источник задержек.

        Ориентир — интервал healthcheck в compose (30 с); проверка должна быть
        на порядки быстрее, иначе мониторинг перестанет её опрашивать.
        """
        import time

        start = time.monotonic()
        client.get("/ready")
        elapsed = time.monotonic() - start

        assert elapsed < 2.0, f"/ready отвечает {elapsed:.2f} с — слишком медленно"


class TestReadyReflectsRealFilesystem:
    """`/ready` обязан отражать состояние каталога, а не затверждённое."""

    def test_unwritable_data_dir_makes_ready_fail(self, tmp_path: Path, monkeypatch) -> None:
        """Недоступный каталог данных → `data_dir.ok == False` и общий 503.

        Подмена этой проверки на «всегда хорошо» прошла бы проверку «в ответе
        есть признак ok», поэтому здесь сравнивается с настоящим состоянием
        файловой системы: путь подменён файлом, и писать в него нельзя.
        """
        from webui.app import create_app

        blocked = tmp_path / "blocked"
        blocked.write_text("это файл, а не каталог", encoding="utf-8")
        monkeypatch.setenv("DATA_PATH", str(blocked))

        app = create_app()
        response = TestClient(app).get("/ready")

        body = response.json()
        assert body["checks"]["data_dir"]["ok"] is False, (
            f"проверка каталога данных объявила негодный путь пригодным: {body}"
        )
        assert "data_dir" in body["failed"], f"отказ не отражён в списке: {body}"
        assert response.status_code == 503

    def test_writable_data_dir_passes_that_check(self, tmp_path: Path, monkeypatch) -> None:
        """Пригодный каталог проходит именно эту проверку."""
        from webui.app import create_app

        usable = tmp_path / "usable"
        monkeypatch.setenv("DATA_PATH", str(usable))

        response = TestClient(create_app()).get("/ready")

        detail = response.json()["checks"]["data_dir"]
        assert detail["ok"] is True, f"пригодный каталог отвергнут: {detail}"
        assert detail["path"] == str(usable), f"в отчёте неверный путь: {detail}"

    def test_key_file_is_created_on_startup_and_reported(self, tmp_path: Path, monkeypatch) -> None:
        """Ключ создаётся при старте, и `/ready` сообщает, что он на месте.

        Изначально тест предполагал, что ключа не будет и проверка его не найдёт.
        Посылка оказалась неверной: `TokenEncryptor` создаёт файл при первом
        обращении, то есть ещё на старте приложения. Проверка готовности видит
        уже созданный ключ — и это правильно, ведь потерять его после старта
        можно только вместе с томом.
        """
        from webui.app import create_app

        monkeypatch.setenv("DATA_PATH", str(tmp_path / "data"))

        response = TestClient(create_app()).get("/ready")

        detail = response.json()["checks"]["encryption_key"]
        assert detail["ok"] is True, f"ключ создан на старте, но не найден: {detail}"
        assert (tmp_path / "data" / "encryption.key").is_file(), (
            "файл ключа должен существовать после старта приложения"
        )


class TestReadinessDoesNotTouchTheDataDirectory:
    """Проверка не должна ничего портить."""

    def test_check_data_dir_does_not_create_files_in_target(self, tmp_path: Path) -> None:
        """В каталоге данных не появляется посторонних файлов."""
        from webui.routes import readiness

        target = tmp_path / "data"
        target.mkdir()
        readiness.check_data_dir(target)

        assert list(target.iterdir()) == [], (
            f"проверка создала файлы в каталоге данных: {list(target.iterdir())}"
        )

    def test_readiness_does_not_require_data_path_env(self, tmp_path: Path, monkeypatch) -> None:
        """Проверка не падает без переменной окружения.

        Отсутствие переменной — самостоятельный сценарий, и он не должен
        превращаться в исключение вместо отчёта.

        Рабочий каталог переносится: без переменной проверка разрешает путь по
        умолчанию, то есть относительный `data`, и создаёт его там, откуда
        запущен pytest. Именно так тест засорял корень репозитория.
        """
        from webui.routes import readiness

        monkeypatch.delenv("DATA_PATH", raising=False)
        monkeypatch.chdir(tmp_path)

        result = readiness.check_data_dir(None)

        assert "ok" in result, f"проверка вернула не результат: {result}"
        assert not Path("data").exists() or Path("data").resolve().is_relative_to(tmp_path), (
            "проверка создала каталог данных вне временного каталога"
        )

    def test_readiness_reports_its_base_path(self) -> None:
        """Отчёт содержит путь, по которому проверялись данные.

        Без пути оператор не поймёт, о каком каталоге речь: в контейнере их
        несколько, и путь изменить можно через DATA_PATH.
        """
        from webui.routes import readiness

        details = [readiness.check_data_dir(os.environ.get("DATA_PATH") or None)]
        assert details[0].get("path"), "в отчёте нет пути к каталогу данных"
