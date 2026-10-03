"""Тесты команды `bulk-import` (спека 009, FR-012, FR-013, FR-015, FR-018).

Команда обнаруживает устройства во внешней системе и вносит их в манифест.
До спеки 009 она не имела ни одного теста: 509 строк кода с интерактивным
вводом, файловыми правками и сетевым обходом.

Тесты идут через штатную точку входа `main()` с подменой `sys.argv`.
Подменяются три вещи: адаптер внешней системы (класс целиком), интерактивный
ввод (заготовленные ответы) и домашний каталог (команда `config` читает
`~/.config/smart_home/bulk_import.yaml`). Ни одна из них не обращается к сети.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from tests.cli import test_bulk_import as cli_module
from tests.cli.conftest import make_state


@pytest.fixture
def lights(fake_ha) -> type:
    """Подготовленный набор устройств: три света, один вентилятор.

    Args:
        fake_ha: Класс заглушки адаптера.

    Returns:
        Класс заглушки с заданными состояниями.
    """
    fake_ha.states = [
        make_state("light.kitchen", "Кухонный свет", area_id="kitchen"),
        make_state("light.living_room", "Свет гостиной", area_id="living_room"),
        make_state("light.bedroom", "Свет спальни", area_id="bedroom"),
        make_state("fan.bathroom", "Вентилятор ванной", area_id="bathroom"),
    ]
    return fake_ha


class TestDiscover:
    """Подкоманда `discover` — просмотр найденного."""

    def test_lists_discovered_devices(self, run_cli, manifest_copy, lights):
        """Команда показывает найденные устройства."""
        code, out, err = run_cli("bulk-import", "-m", str(manifest_copy), "discover")

        assert code == 0, f"ожидался 0: {err}"
        assert "Total devices" in out, f"ожидался итог подсчёта: {out[:400]}"
        assert "light.kitchen" in out, f"ожидалось устройство в списке: {out[:400]}"

    def test_reports_domain_summary(self, run_cli, manifest_copy, lights):
        """Вывод содержит сводку по доменам."""
        _, out, _ = run_cli("bulk-import", "-m", str(manifest_copy), "discover")

        assert "By Domain" in out, f"ожидалась сводка по доменам: {out[:400]}"
        assert "light" in out, f"домен light должен быть в сводке: {out[:400]}"

    def test_reports_total_count(self, run_cli, manifest_copy, lights):
        """Итог совпадает с числом подготовленных устройств."""
        _, out, _ = run_cli("bulk-import", "-m", str(manifest_copy), "discover")

        assert "Total devices: 4" in out, f"ожидалось 4 устройства: {out[:400]}"

    def test_filter_by_domain_narrows_result(self, run_cli, manifest_copy, lights):
        """Фильтр по домену ограничивает выдачу."""
        _, all_out, _ = run_cli("bulk-import", "-m", str(manifest_copy), "discover")
        _, filtered, _ = run_cli(
            "bulk-import", "-m", str(manifest_copy), "discover", "--filter-domain", "fan"
        )

        assert "Total devices: 4" in all_out
        assert "Total devices: 1" in filtered, f"фильтр не сузил выдачу: {filtered[:400]}"
        assert "fan.bathroom" in filtered
        assert "light.kitchen" not in filtered, "свет не должен попасть в фильтр по fan"

    def test_discover_does_not_modify_manifest(self, run_cli, manifest_copy, lights):
        """Просмотр не меняет манифест.

        Команда только читает; изменение файла означало бы не запрошенный
        пользователем побочный эффект.
        """
        before = manifest_copy.read_text(encoding="utf-8")

        run_cli("bulk-import", "-m", str(manifest_copy), "discover")

        assert manifest_copy.read_text(encoding="utf-8") == before, "манифест не должен меняться"

    def test_empty_system_lists_nothing(self, run_cli, manifest_copy, fake_ha):
        """Пустая внешняя система даёт нулевой итог, а не ошибку."""
        fake_ha.states = []

        code, out, err = run_cli("bulk-import", "-m", str(manifest_copy), "discover")

        assert code == 0, f"ожидался 0: {err}"
        assert "Total devices: 0" in out, f"ожидался нулевой итог: {out[:400]}"


class TestUnavailableSystem:
    """Недоступность внешней системы — штатный проверяемый сценарий."""

    def test_unavailable_system_fails_readably(self, run_cli, manifest_copy, fake_ha):
        """Отказ подключения: ненулевой код и сообщение без трассировки."""
        fake_ha.connected = False

        code, _, err = run_cli("bulk-import", "-m", str(manifest_copy), "discover")

        assert code != 0, "ожидался ненулевой код возврата"
        assert "not connected" in err.lower(), f"сообщение должно называть причину: {err}"
        assert "Traceback" not in err, f"трассировка не должна показываться: {err}"

    def test_unavailable_system_leaves_manifest_untouched(self, run_cli, manifest_copy, fake_ha):
        """Недоступность системы не изменяет манифест.

        Это проверка отката: команда меняет конфигурацию, и отказ до всякой
        правки обязан оставить её в исходном состоянии.
        """
        fake_ha.connected = False
        before = manifest_copy.read_text(encoding="utf-8")

        run_cli("bulk-import", "-m", str(manifest_copy), "discover")

        assert manifest_copy.read_text(encoding="utf-8") == before, "манифест не должен меняться"


class TestApply:
    """Подкоманда `apply` — внесение устройств в манифест."""

    def test_apply_reports_result(self, run_cli, manifest_copy, lights):
        """Команда сообщает о результате применения."""
        code, out, err = run_cli("bulk-import", "-m", str(manifest_copy), "apply")

        assert code == 0, f"ожидался 0: {err}"
        assert "Apply Results" in out or "Dry Run" in out, f"ожидался отчёт: {out[:400]}"

    def test_dry_run_does_not_change_manifest(self, run_cli, manifest_copy, lights):
        """Пробный прогон не меняет манифест.

        Ключевое свойство: `--dry-run` обещает показать, что будет сделано,
        не сделав этого. Без проверки обещание осталось бы декларацией.
        """
        before = manifest_copy.read_text(encoding="utf-8")

        code, out, err = run_cli("bulk-import", "-m", str(manifest_copy), "apply", "--dry-run")

        assert code == 0, f"ожидался 0: {err}"
        assert manifest_copy.read_text(encoding="utf-8") == before, (
            "пробный прогон обязан оставить манифест неизменным"
        )
        assert "Dry Run" in out, f"ожидался вывод пробного прогона: {out[:400]}"

    def test_missing_manifest_fails_with_path(self, run_cli, tmp_path):
        """Отсутствующий манифест: ненулевой код и названный путь."""
        missing = tmp_path / "нет.yaml"

        code, _, err = run_cli("bulk-import", "-m", str(missing), "apply")

        assert code != 0, "ожидался ненулевой код возврата"
        assert str(missing) in err, f"сообщение должно называть путь: {err}"

    def test_missing_manifest_does_not_create_it(self, run_cli, tmp_path):
        """Отказ не создаёт манифест на месте отсутствующего.

        Команда, которая при ошибке создаёт пустой файл, способна затереть
        последующую работу пользователя, решившего, что файл не найден.
        """
        missing = tmp_path / "нет.yaml"

        run_cli("bulk-import", "-m", str(missing), "apply")

        assert not missing.exists(), "файл не должен появляться после отказа"


class TestInteractive:
    """Подкоманда `interactive` — выбор устройств вручную."""

    def test_declined_device_is_skipped(self, run_cli, manifest_copy, lights, scripted_input):
        """Отказ от устройства не добавляет его."""
        scripted_input(["n", "n", "n", "n"])

        code, out, err = run_cli("bulk-import", "-m", str(manifest_copy), "interactive")

        assert code == 0, f"ожидался 0: {err}"
        assert "No devices selected" in out, f"ожидалось сообщение о пустом выборе: {out[:500]}"

    def test_all_declined_leaves_manifest_untouched(
        self, run_cli, manifest_copy, lights, scripted_input
    ):
        """Полный отказ не меняет манифест."""
        scripted_input(["n", "n", "n", "n"])
        before = manifest_copy.read_text(encoding="utf-8")

        run_cli("bulk-import", "-m", str(manifest_copy), "interactive")

        assert manifest_copy.read_text(encoding="utf-8") == before, "манифест не должен меняться"

    def test_cancelled_apply_leaves_manifest_untouched(
        self, run_cli, manifest_copy, lights, scripted_input
    ):
        """Отмена на вопросе о применении оставляет манифест неизменным.

        Сценарий: устройство выбрано, предпросмотр выполнен, но пользователь
        отвечает «нет» на подтверждение. Наивная реализация применила бы
        изменения до вопроса — тест это ловит.
        """
        # y — принять устройство, 1 — выбрать предложенную комнату,
        # y — взять предложенное поведение, n — отменить применение
        scripted_input(["y", "1", "y", "n"])
        before = manifest_copy.read_text(encoding="utf-8")

        code, out, err = run_cli("bulk-import", "-m", str(manifest_copy), "interactive")

        assert code == 0, f"ожидался 0: {err}"
        assert "Cancelled" in out, f"ожидалось сообщение об отмене: {out[:600]}"
        assert manifest_copy.read_text(encoding="utf-8") == before, (
            "отмена не должна оставлять применённые изменения"
        )

    def test_preview_runs_before_confirmation(self, run_cli, manifest_copy, lights, scripted_input):
        """Предпросмотр выполняется до вопроса о применении.

        Пользователь должен увидеть, что именно изменится, прежде чем
        соглашаться. Порядок проверяется на выводе: предпросмотр обязан
        напечатать число добавляемых устройств.
        """
        scripted_input(["y", "1", "y", "n"])

        _, out, _ = run_cli("bulk-import", "-m", str(manifest_copy), "interactive")

        assert "Preview" in out, f"ожидался предпросмотр: {out[:600]}"
        assert "Would add" in out, f"ожидалось число добавляемых: {out[:600]}"
        preview_at = out.index("Would add")
        confirm_at = out.index("Apply changes?")
        assert preview_at < confirm_at, "предпросмотр должен идти до подтверждения"

    def test_missing_manifest_fails_before_asking_anything(
        self, run_cli, tmp_path, lights, scripted_input
    ):
        """Отсутствующий манифест отвергается до первого вопроса.

        Проверяется отсутствием вопросов: если бы команда спрашивала, значит
        проверка пути выполнена не в начале.
        """
        asked: list[str] = []

        import builtins

        original = builtins.input
        builtins.input = lambda prompt="": asked.append(prompt) or "n"  # type: ignore[assignment]
        try:
            code, _, err = run_cli("bulk-import", "-m", str(tmp_path / "нет.yaml"), "interactive")
        finally:
            builtins.input = original

        assert code != 0, "ожидался ненулевой код возврата"
        assert not asked, f"пользователю не задавали вопросов: {asked}"
        assert str(tmp_path / "нет.yaml") in err


class TestConfig:
    """Подкоманда `config` — работа с файлом настроек."""

    def test_show_without_config_explains_absence(self, run_cli, manifest_copy, cli_home):
        """Отсутствие настроек объясняется, а не молчит."""
        code, out, _ = run_cli("bulk-import", "-m", str(manifest_copy), "config", "--show")

        assert code == 0, f"ожидался 0: {out}"
        assert "No configuration found" in out, f"ожидалось объяснение: {out}"

    def test_show_prints_existing_config(self, run_cli, manifest_copy, cli_home):
        """Существующие настройки выводятся пользователю."""
        config = cli_home / ".config" / "smart_home"
        config.mkdir(parents=True)
        (config / "bulk_import.yaml").write_text("ws_url: ws://example\n", encoding="utf-8")

        code, out, _ = run_cli("bulk-import", "-m", str(manifest_copy), "config", "--show")

        assert code == 0, f"ожидался 0: {out}"
        assert "ws_url" in out, f"ожидалось содержимое настроек: {out}"

    def test_config_reads_home_of_current_run(self, run_cli, manifest_copy, cli_home):
        """Настройки читаются из подменённого домашнего каталога.

        Проверяет саму изоляцию фикстуры: команда обязана читать
        `~/.config/smart_home/`, а не путь настоящего пользователя.
        """
        config = cli_home / ".config" / "smart_home"
        config.mkdir(parents=True)
        (config / "bulk_import.yaml").write_text(
            "marker: из-временного-каталога\n", encoding="utf-8"
        )

        _, out, _ = run_cli("bulk-import", "-m", str(manifest_copy), "config", "--show")

        assert "из-временного-каталога" in out, f"ожидались настройки из временного каталога: {out}"


class TestFailureScenarios:
    """Ошибочные сценарии — каждый обязан давать понятный отказ."""

    def test_unknown_subcommand_fails(self, run_cli, manifest_copy):
        """Неизвестная подкоманда отклоняется разбором аргументов."""
        with pytest.raises(SystemExit) as excinfo:
            run_cli("bulk-import", "-m", str(manifest_copy), "такой-подкоманды")

        assert excinfo.value.code != 0, "ожидался ненулевой код возврата"

    def test_missing_required_manifest_fails(self, run_cli):
        """Обязательный `-m` отсутствует — разбор это отклоняет."""
        with pytest.raises(SystemExit) as excinfo:
            run_cli("bulk-import", "discover")

        assert excinfo.value.code != 0, "ожидался ненулевой код возврата"

    def test_help_lists_subcommands(self, run_cli, capsys):
        """Справка перечисляет подкоманды."""
        with pytest.raises(SystemExit):
            run_cli("bulk-import", "--help")

        captured = capsys.readouterr()
        combined = captured.out + captured.err

        for name in ("interactive", "discover", "apply", "config"):
            assert name in combined, f"справка должна содержать подкоманду {name}: {combined}"


#: Корни модулей стандартного и внешнего сетевого стека. Сравнение идёт по
#: первому сегменту имени (`urllib.request` → `urllib`), иначе весь сетевой
#: стек проходит мимо проверки.
NETWORK_ROOTS = frozenset(
    {
        "urllib",
        "http",
        "httpx",
        "requests",
        "aiohttp",
        "socket",
        "ssl",
        "ftplib",
        "smtplib",
        "poplib",
        "imaplib",
        "xmlrpc",
        "pycurl",
        "urllib3",
    }
)


def _collect_offenders(source: str) -> list[str]:
    """Собирает сетевые вызовы и запуски процессов в исходном коде.

    Разбор идёт по дереву синтаксиса, а не по тексту: текстовый поиск находил
    бы саму проверку — собственные строки с именами модулей. Данные вида
    `ws://example` внутри YAML при этом законны, потому что сетевым
    обращением считается импорт или вызов, а не текст в строке.

    Args:
        source: Исходный код для разбора.

    Returns:
        Список найденных обращений.
    """
    tree = ast.parse(source.strip())
    offenders: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in NETWORK_ROOTS:
                    offenders.append(f"импорт {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in NETWORK_ROOTS:
                offenders.append(f"импорт из {node.module}")
            for alias in node.names:
                if alias.name in {"urlopen", "create_connection"}:
                    offenders.append(f"вызов {alias.name}")
        elif isinstance(node, ast.Attribute) and node.attr in {
            "urlopen",
            "create_connection",
            "system",
        }:
            offenders.append(f"вызов {node.attr}")

    return offenders


class TestIsolation:
    """Команда не выходит в сеть и не пишет в репозиторий."""

    def test_cli_tests_do_not_touch_network_or_processes(self):
        """Тесты интерфейса не обращаются по сети и не запускают процессы.

        Иначе результат зависел бы от наличия Home Assistant в сети машины, а
        каждый тест порождал бы процесс вместо вызова.
        """
        offenders: list[str] = []
        for name in ("test_bulk_import.py", "test_export_fsm.py", "conftest.py"):
            path = pathlib.Path(cli_module.__file__).parent / name
            offenders.extend(
                f"{name}: {item}" for item in _collect_offenders(path.read_text("utf-8"))
            )

        assert not offenders, f"тесты не должны обращаться по сети: {offenders}"

    def test_manifest_untouched_across_all_subcommands(
        self, run_cli, manifest_copy, lights, scripted_input
    ):
        """Ни одна подкоманда не меняет манифест в неожиданном месте.

        Прогоняются все подкоманды подряд; сравнивается содержимое до и после.
        """
        scripted_input(["n", "n", "n", "n"])
        before = manifest_copy.read_text(encoding="utf-8")

        run_cli("bulk-import", "-m", str(manifest_copy), "discover")
        run_cli("bulk-import", "-m", str(manifest_copy), "apply", "--dry-run")
        run_cli("bulk-import", "-m", str(manifest_copy), "interactive")
        run_cli("bulk-import", "-m", str(manifest_copy), "config", "--show")

        assert manifest_copy.read_text(encoding="utf-8") == before, (
            "ни одна из прогнанных подкоманд не должна была менять манифест"
        )

    def test_adapter_is_started_and_stopped(self, run_cli, manifest_copy, lights):
        """Адаптер внешней системы запускается и останавливается.

        Проверка на освобождение ресурса: `stop()` стоит в `finally`, и если
        его убрать, соединение оставалось бы висеть после каждой команды.
        """
        created: list[object] = []
        original_init = lights.__init__

        def tracking_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            created.append(self)

        lights.__init__ = tracking_init  # type: ignore[method-assign]
        try:
            run_cli("bulk-import", "-m", str(manifest_copy), "discover")
        finally:
            lights.__init__ = original_init  # type: ignore[method-assign]

        assert created, "адаптер должен был быть создан"
        assert all(adapter.stop_calls == 1 for adapter in created), (
            f"адаптер обязан быть остановлен: {[(a.start_calls, a.stop_calls) for a in created]}"
        )
