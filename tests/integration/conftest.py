"""Инфраструктура интеграционных тестов: идентичность, изоляция, заглушка.

Спека `specs/009-test-coverage`, FR-001…FR-004, FR-010, FR-026; решения
R-02, R-03, R-04. Фичи F4.

Зачем эта инфраструктура
------------------------
Измерение 2026-10-03 показало три независимые причины, по которым заявленные
тесты не выполнялись или выполнялись вхолостую:

1. **Отсутствие идентичности.** `DeviceAccessMiddleware`
   (`src/webui/middleware_access_control.py:38-91`) отклоняет с 401 любой
   запрос под `/api/v1/devices/**`, кроме ровно двух исключений:
   `GET /api/v1/devices` и `POST /api/v1/devices/sources`. Пять тестов падали
   на 401 именно потому, что эти два запроса шли без заголовка.

   Отдельная ловушка: `GET /api/v1/devices` **никогда не даёт 401** — без
   идентичности он возвращает `200 []` (`devices.py:136-138`). То есть
   «успешный» ответ списка без прав вообще не является проверкой прав.

2. **Зависимость от сети машины.** Один тест доходил до реального
   подключения к `192.168.1.100:8123`, потому что подменял выдачу устройств,
   но не подключение.

3. **Запись в рабочий каталог репозитория.** `create_app` собирает
   `PersistenceManager(data_dir="data")` — относительный путь, который
   разрешается от текущего каталога при каждой записи (`app.py:367`).
   Измерением зафиксировано: полный прогон растит `data/sources.json`
   на 34 КБ за запуск, а в каталоге накопилось 2580 источников — следы
   прошлых прогонов, а не данные установки.

Идентичность и изоляция решаются здесь, один раз, чтобы волна правок US4
не могла про них забыть: тест, забывший заголовок, обязан падать на 401,
а не «проходить вхолостую».

Приём изоляции
--------------
Работающий приём уже применяется в проекте
(`tests/integration/test_device_sync_lifecycle.py:63-84`): временный каталог
+ `os.chdir` + копия манифеста + `create_app(str(manifest))`. Он изолирует
сразу все файлы (`sources.json`, `devices.json`, `device_access.json`,
`device_sync_events.json`, `state.json`), потому что все они заданы
относительными путями.

Два ограничения приёма, которые здесь зафиксированы намеренно:

- `os.chdir` — процессно-глобальный, а не потокобезопасный. Приём пригоден,
  пока тесты выполняются последовательно (текущий режим pytest).
- `os.chdir` **не действует на `from main import app`**: этот объект
  создаётся при импорте модуля и замыкает пути. Изолированные фикстуры
  поэтому собирают приложение через `create_app`, а не берут синглтон.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tests.helpers.ha_stub import HAUnavailable, stub_ha

from core.persistence.event_store import EventStore


#: Заголовки администратора. Админ проходит проверку прав всегда
#: (`devices.py:65-66`), поэтому используется как роль по умолчанию.
ADMIN_HEADERS = {"X-Is-Admin": "true"}

#: Каталог с манифестом, который копируется во временный рабочий каталог.
MANIFEST_RELPATH = Path("instances") / "leonids_house" / "manifest.yaml"

#: Идентификатор пользователя без каких-либо прав.
NO_RIGHTS_USER_ID = "user_without_rights"

#: Идентификатор пользователя для сценариев доступа и событий.
REGULAR_USER_ID = "regular_user"

#: Идентификатор пользователя с ролью только для чтения.
VIEWER_USER_ID = "user_viewer"

#: Идентификатор второго пользователя, отличный от первого по набору прав.
OTHER_USER_ID = "user_other"


def _headers(user_id: str, is_admin: bool = False) -> dict[str, str]:
    """Собирает заголовки идентичности пользователя.

    Args:
        user_id: Идентификатор пользователя.
        is_admin: Является ли пользователь администратором.

    Returns:
        Заголовки запроса.
    """
    headers = {"X-User-ID": user_id}
    if is_admin:
        headers["X-Is-Admin"] = "true"
    return headers


@pytest.fixture
def project_root() -> Path:
    """Возвращает корень репозитория.

    Returns:
        Путь к корню репозитория.
    """
    return Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def isolated_workdir(project_root: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Изолирует файлы данных теста во временном рабочем каталоге.

    Изоляция задаётся через `DATA_PATH`, потому что это единственный механизм,
    который работает всегда: `resolve_data_dir()` читает переменную при КАЖДОМ
    вызове, и путь берётся абсолютный, а не относительный.

    Раньше здесь был только `os.chdir()` в расчёте на то, что `data_dir="data"`
    — относительный путь, который разрешится от текущего каталога. Эта
    изоляция оказывалась хрупкой: она не действовала, если `DATA_PATH` задан
    снаружи (например, в tests/conftest.py ради защиты корня репозитория), и
    тогда все тесты модуля писали в общий каталог. Именно так проявились 22
    падения: тесты на синхронизацию видели 12 источников вместо одного, потому
    что состояние накапливалось между тестами.

    `os.chdir` сохранён: манифест и относительные пути конфигурации тоже
    разрешаются от него.

    Yields:
        Путь к временному рабочему каталогу.
    """
    work_dir = Path(tempfile.mkdtemp(prefix="shp_integration_"))
    manifest = project_root / MANIFEST_RELPATH
    shutil.copy(manifest, work_dir / "manifest.yaml")
    monkeypatch.setenv("DATA_PATH", str(work_dir / "data"))
    previous_cwd = os.getcwd()
    os.chdir(work_dir)
    try:
        yield work_dir
    finally:
        os.chdir(previous_cwd)
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.fixture(autouse=True)
def reset_module_level_stores() -> Iterator[None]:
    """Обнулять хранилища, созданные на уровне модуля, после каждого теста.

    ``webui.routes`` держит ``event_store``, созданный **при импорте**: путь к базе
    вычисляется один раз. Тесты изолируются через ``DATA_PATH``, поэтому база
    указывает на временный каталог, который следующая проверка удаляет, — и
    падение вылезает не там, где причина: ``/api/overrides`` отвечал «unable to open
    database file» только в общем прогоне, а по одиночке проходил.

    Returns:
        Ничего.
    """
    yield
    from webui import routes as webui_routes

    if getattr(webui_routes, "event_store", None) is not None:
        webui_routes.event_store = EventStore()


@pytest.fixture
def repo_data_guard(project_root: Path) -> Iterator[dict[str, int]]:
    """Следит за тем, чтобы каталог `data/` репозитория не изменился.

    Фикстура не может запретить запись — она её обнаруживает. Значение
    снимка доступно тесту, чтобы при провале самого теста можно было сказать,
    что именно протекало наружу.

    Yields:
        Снимок размеров файлов каталога данных на момент старта.
    """
    data_dir = project_root / "data"
    before = _dir_sizes(data_dir)
    yield before
    after = _dir_sizes(data_dir)
    assert after == before, (
        "Тест изменил каталог `data/` репозитория — нарушено требование "
        f"изоляции хранилища (FR-026). Изменились: {_diff(before, after)}"
    )


def _dir_sizes(data_dir: Path) -> dict[str, int]:
    """Собирает размеры файлов каталога данных.

    Args:
        data_dir: Каталог данных.

    Returns:
        Соответствие «имя файла → размер в байтах».
    """
    if not data_dir.exists():
        return {}
    return {p.name: p.stat().st_size for p in sorted(data_dir.glob("*")) if p.is_file()}


def _diff(before: dict[str, int], after: dict[str, int]) -> dict[str, tuple[int, int]]:
    """Вычисляет различия между двумя снимками каталога.

    Args:
        before: Первый снимок.
        after: Второй снимок.

    Returns:
        Соответствие «имя файла → (было, стало)» для изменившихся файлов.
    """
    names = set(before) | set(after)
    return {
        n: (before.get(n, 0), after.get(n, 0))
        for n in sorted(names)
        if before.get(n) != after.get(n)
    }


@pytest.fixture
def isolated_app(isolated_workdir: Path) -> Any:
    """Собирает приложение на изолированном хранилище.

    Приложение создаётся через `create_app`, а не берётся из `src.main`:
    синглтон `src.main.app` создаётся при импорте модуля и замыкает пути
    до входа в фикстуру, поэтому изоляция на него не действует.

    Args:
        isolated_workdir: Временный рабочий каталог.

    Returns:
        Приложение FastAPI.
    """
    from webui.app import create_app

    return create_app(str(isolated_workdir / "manifest.yaml"))


@pytest.fixture
def admin_user_id() -> str:
    """Идентификатор администратора.

    Returns:
        Идентификатор пользователя с административными правами.
    """
    return "admin_user"


@pytest.fixture
def admin_headers(admin_user_id: str) -> dict[str, str]:
    """Заголовки администратора.

    Returns:
        Заголовки, передаваемые в клиент по умолчанию.
    """
    return _headers(admin_user_id, is_admin=True)


@pytest.fixture
def regular_user_id() -> str:
    """Идентификатор обычного пользователя.

    Имена прежних фикстур (`regular_user_id`, `another_user_id`) жили в самих
    тестовых файлах. Сведение идентичностей в `conftest.py` означает, что
    удаление одного файла больше не оставляет тесты без фикстуры.

    Returns:
        Идентификатор пользователя без административных прав.
    """
    return REGULAR_USER_ID


@pytest.fixture
def no_rights_headers() -> dict[str, str]:
    """Заголовки пользователя без прав доступа к устройствам.

    Returns:
        Заголовки пользователя без записей доступа.
    """
    return _headers(NO_RIGHTS_USER_ID)


@pytest.fixture
def viewer_headers() -> dict[str, str]:
    """Заголовки пользователя с ролью только для чтения.

    Returns:
        Заголовки пользователя с ролью viewer.
    """
    return _headers(VIEWER_USER_ID)


@pytest.fixture
def other_headers() -> dict[str, str]:
    """Заголовки второго пользователя, отличного от остальных.

    Returns:
        Заголовки второго пользователя.
    """
    return _headers(OTHER_USER_ID)


@pytest.fixture
def isolated_client(isolated_app: Any, admin_headers: dict[str, str]) -> Iterator[TestClient]:
    """Клиент по умолчанию от имени администратора.

    Args:
        isolated_app: Приложение на изолированном хранилище.
        admin_headers: Заголовки администратора.

    Yields:
        HTTP-клиент теста.
    """
    with TestClient(isolated_app, headers=admin_headers) as client:
        yield client


@pytest.fixture
def ha_states() -> list[dict[str, Any]]:
    """Стандартный набор состояний внешней системы.

    Returns:
        Список состояний двух устройств в формате Home Assistant.
    """
    return [
        {
            "entity_id": "light.kitchen",
            "state": "on",
            "attributes": {"friendly_name": "Кухонный свет", "brightness": 255},
        },
        {
            "entity_id": "switch.bedroom_fan",
            "state": "off",
            "attributes": {"friendly_name": "Вентилятор спальни"},
        },
    ]


@pytest.fixture
def synced_device_id(isolated_client: TestClient, ha_states: list[dict[str, Any]]) -> str:
    """Устройство, полученное реальной синхронизацией источника.

    Отличается от посева в память: устройство проходит весь путь от HTTP-запроса
    до персистентности, поэтому существует и в сервисе, и на диске.

    Args:
        isolated_client: HTTP-клиент теста.
        ha_states: Состояния внешней системы.

    Returns:
        Идентификатор синхронизированного устройства.
    """
    source = isolated_client.post(
        "/api/v1/devices/sources",
        json={
            "name": "Fixture HA",
            "url": "http://ha.invalid:8123",
            "token": "fixture_token_12345",
        },
    )
    assert source.status_code == 201, source.text
    source_id = str(source.json()["id"])

    with stub_ha(states=ha_states):
        sync = isolated_client.post(f"/api/v1/devices/sources/{source_id}/sync")
    assert sync.status_code == 200, sync.text

    devices = isolated_client.get("/api/v1/devices").json()
    assert devices, "синхронизация не создала ни одного устройства"
    return str(devices[0]["id"])


@pytest.fixture
def grant_viewer(isolated_client: TestClient, synced_device_id: str) -> str:
    """Выдаёт роль только для чтения пользователю из `viewer_headers`.

    Args:
        isolated_client: HTTP-клиент теста.
        synced_device_id: Идентификатор устройства.

    Returns:
        Идентификатор записи о доступе.
    """
    response = isolated_client.post(
        f"/api/v1/devices/{synced_device_id}/access",
        json={"user_id": VIEWER_USER_ID, "role": "viewer"},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


@pytest.fixture
def ha_unavailable(isolated_client: TestClient) -> str:
    """Идентификатор источника, синхронизация которого гарантированно не удастся.

    Args:
        isolated_client: HTTP-клиент теста.

    Returns:
        Идентификатор созданного источника.
    """
    response = isolated_client.post(
        "/api/v1/devices/sources",
        json={
            "name": "Unreachable HA",
            "url": "http://unreachable.invalid:8123",
            "token": "unreachable_token_123",
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


@pytest.fixture
def ha_refused() -> Iterator[None]:
    """Перехватывает обращение к внешней системе: соединение отклонено.

    Yields:
        None.
    """
    with stub_ha(mode=HAUnavailable.REFUSED):
        yield


@pytest.fixture
def ha_timeout() -> Iterator[None]:
    """Перехватывает обращение к внешней системе: истекает время ожидания.

    Yields:
        None.
    """
    with stub_ha(mode=HAUnavailable.TIMEOUT):
        yield


@pytest.fixture
def ha_client(isolated_app: Any) -> Any:
    """Экземпляр клиента внешней системы для проверок на уровне клиента.

    Args:
        isolated_app: Приложение на изолированном хранилище.

    Returns:
        Экземпляр ``HARestClient``.
    """
    from adapters.home_assistant.rest_client import HARestClient

    return HARestClient("http://ha.invalid:8123", "client_token_12345")
