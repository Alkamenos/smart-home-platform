"""Тесты команды `export-fsm` (спека 009, FR-009…FR-011, FR-014).

Команда выгружает схемы автоматов из манифеста в Mermaid или Graphviz. До
спеки 009 она не имела ни одного теста: 755 строк `bulk_import.py` и весь
`export_fsm.py` были без покрытия.

Все тесты идут через штатную точку входа `smart_home.cli.main.main()`, а не
через внутренние функции: иначе не проверялись бы разбор аргументов и код
возврата — то есть ровно то, где команда ломается у пользователя.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import pytest


class TestSuccessfulExport:
    """Успешная выгрузка схем."""

    def test_exports_mermaid_to_stdout(self, run_cli, manifest_copy):
        """Схема выводится в стандартный вывод."""
        code, out, err = run_cli("export-fsm", str(manifest_copy))

        assert code == 0, f"ожидался 0, получено {code}: {err}"
        assert out.strip(), "вывод не должен быть пустым"
        assert "stateDiagram" in out or "state " in out, f"ожидалась схема Mermaid: {out[:300]}"

    def test_exports_to_file_when_output_given(self, run_cli, manifest_copy, tmp_path):
        """Схема записывается в файл, а не печатается."""
        target = tmp_path / "nested" / "scheme.md"

        code, out, _ = run_cli("export-fsm", str(manifest_copy), "--output", str(target))

        assert code == 0, out
        assert target.exists(), "файл схемы должен быть создан"
        content = target.read_text(encoding="utf-8")
        assert content.strip(), "файл схемы не должен быть пустым"
        assert "state" in content, f"ожидалась схема: {content[:200]}"

    def test_creates_missing_parent_directories(self, run_cli, manifest_copy, tmp_path):
        """Отсутствующие каталоги создаются — иначе команда падает на вводе пути."""
        target = tmp_path / "a" / "b" / "c" / "scheme.md"

        code, out, _ = run_cli("export-fsm", str(manifest_copy), "-o", str(target))

        assert code == 0, out
        assert target.exists(), "вложенные каталоги должны быть созданы"

    def test_reports_destination_path(self, run_cli, manifest_copy, tmp_path):
        """Пользователю сообщается, куда записана схема."""
        target = tmp_path / "scheme.mmd"

        _, out, _ = run_cli("export-fsm", str(manifest_copy), "--output", str(target))

        assert str(target) in out, f"путь должен быть назван: {out}"

    def test_graphviz_format_is_supported(self, run_cli, manifest_copy):
        """Формат graphviz даёт DOT-разметку."""
        code, out, err = run_cli("export-fsm", str(manifest_copy), "--format", "graphviz")

        assert code == 0, f"ожидался 0: {err}"
        assert "digraph" in out, f"ожидалась DOT-разметка: {out[:300]}"

    def test_mermaid_is_default_format(self, run_cli, manifest_copy):
        """Mermaid используется по умолчанию."""
        _, default_out, _ = run_cli("export-fsm", str(manifest_copy))
        _, explicit_out, _ = run_cli("export-fsm", str(manifest_copy), "--format", "mermaid")

        assert default_out == explicit_out, "формат по умолчанию должен совпадать с -f mermaid"


class TestDeviceFilter:
    """Фильтрация по устройству."""

    def test_filter_returns_only_that_device(self, run_cli, manifest_copy):
        """Фильтр ограничивает вывод автоматами одного устройства."""
        code, all_out, err = run_cli("export-fsm", str(manifest_copy))
        assert code == 0, err

        code, filtered, err = run_cli("export-fsm", str(manifest_copy), "--device", "light.kitchen")
        assert code == 0, err

        assert filtered.strip(), "фильтр обязан дать непустой вывод"
        assert filtered != all_out, "фильтр должен отличаться от полного вывода"

    def test_filter_of_known_device_mentions_it(self, run_cli, manifest_copy):
        """Отфильтрованный вывод содержит имя устройства."""
        _, out, _ = run_cli("export-fsm", str(manifest_copy), "-d", "light.kitchen")

        assert "light.kitchen" in out, f"имя устройства должно присутствовать: {out[:300]}"

    def test_filter_of_unknown_device_fails(self, run_cli, manifest_copy):
        """Фильтр по несуществующему устройству — ненулевой код с пояснением."""
        code, _, err = run_cli("export-fsm", str(manifest_copy), "--device", "light.does_not_exist")

        assert code != 0, "ожидался ненулевой код возврата"
        assert "light.does_not_exist" in err, f"сообщение должно называть устройство: {err}"

    def test_filter_result_is_stricter_than_unfiltered(self, run_cli, manifest_copy):
        """Фильтр уменьшает объём вывода.

        Проверка на размере, а не на «строки отличаются»: иначе тест прошёл бы
        и при фильтре, который добавляет информацию вместо того, чтобы её
        убирать.
        """
        _, all_out, _ = run_cli("export-fsm", str(manifest_copy))
        _, filtered, _ = run_cli("export-fsm", str(manifest_copy), "-d", "light.kitchen")

        assert len(filtered) < len(all_out), "отфильтрованный вывод должен быть короче полного"


class TestFailureScenarios:
    """Ошибочные сценарии — каждый обязан давать понятный отказ."""

    def test_missing_manifest_fails_with_path(self, run_cli, tmp_path):
        """Отсутствующий манифест: ненулевой код и названный путь."""
        missing = tmp_path / "нет-такого.yaml"

        code, _, err = run_cli("export-fsm", str(missing))

        assert code != 0, "ожидался ненулевой код возврата"
        assert str(missing) in err, f"сообщение должно называть путь: {err}"

    def test_missing_manifest_prints_no_traceback(self, run_cli, tmp_path, capsys):
        """Пользователю не показывается внутренняя трассировка.

        Наличие `Traceback` в выводе означало бы, что ошибка не обработана:
        код упал и пользователь получил отладочное сообщение вместо ответа.
        """
        run_cli("export-fsm", str(tmp_path / "нет.yaml"))

        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "Traceback" not in combined, (
            f"трассировка не должна попадать к пользователю: {combined}"
        )
        assert 'File "' not in combined, f"пути файлов не должны утекать: {combined}"

    def test_corrupted_manifest_fails_readably(self, run_cli, broken_manifest):
        """Повреждённый манифест: понятное сообщение без трассировки."""
        code, _, err = run_cli("export-fsm", str(broken_manifest))

        assert code != 0, "ожидался ненулевой код возврата"
        assert err.strip(), "сообщение об ошибке должно быть"
        assert "Traceback" not in err, f"трассировка не должна показываться: {err}"

    def test_manifest_without_fsms_fails(self, run_cli, tmp_path):
        """Манифест без автоматов: ненулевой код."""
        empty = tmp_path / "empty.yaml"
        empty.write_text("rooms: []\n", encoding="utf-8")

        code, _, err = run_cli("export-fsm", str(empty))

        assert code != 0, "ожидался ненулевой код возврата"
        assert "No FSMs" in err or "no fsm" in err.lower(), (
            f"сообщение должно говорить об отсутствии автоматов: {err}"
        )

    def test_unknown_format_is_rejected(self, run_cli, manifest_copy):
        """Неизвестный формат отклоняется разбором аргументов.

        argparse сообщает об ошибке через `parser.exit(2)`, то есть
        исключением `SystemExit`, а не кодом возврата. Поэтому вызов
        оборачивается — иначе тест упал бы с `SystemExit` вместо проверки
        отказа, и проверял бы не поведение команды.
        """
        with pytest.raises(SystemExit) as excinfo:
            run_cli("export-fsm", str(manifest_copy), "--format", "png")

        assert excinfo.value.code != 0, "ожидался ненулевой код возврата"

    def test_unknown_command_shows_help(self, run_cli, capsys):
        """Неизвестная команда: справка со списком команд."""
        with pytest.raises(SystemExit) as excinfo:
            run_cli("такой-команды-нет")

        code = excinfo.value.code
        captured = capsys.readouterr()
        combined = captured.out + captured.err

        assert code != 0, "ожидался ненулевой код возврата"
        assert "export-fsm" in combined, f"справка должна перечислять команды: {combined}"
        assert "bulk-import" in combined, f"справка должна перечислять команды: {combined}"

    def test_no_arguments_shows_help_and_succeeds(self, run_cli, capsys):
        """Запуск без аргументов показывает справку и возвращает 0."""
        code, out, _ = run_cli()

        assert code == 0, "запуск без аргументов не должен считаться ошибкой"
        assert "usage" in out.lower() or "Available commands" in out, (
            f"без аргументов ожидалась справка: {out}"
        )

    def test_missing_required_manifest_argument_fails(self, run_cli):
        """Обязательный аргумент манифеста отсутствует — разбор это отклоняет."""
        with pytest.raises(SystemExit) as excinfo:
            run_cli("export-fsm")

        assert excinfo.value.code != 0, "ожидался ненулевой код возврата"


class TestOutputDeterminism:
    """Один и тот же вход даёт один и тот же вывод."""

    def test_repeated_runs_are_identical(self, run_cli, manifest_copy):
        """Повторный запуск даёт идентичный вывод.

        Команда не должна зависеть от порядка запусков или накопленного
        состояния — иначе выгруженную схему нельзя было бы сверять вручную.
        """
        _, first, _ = run_cli("export-fsm", str(manifest_copy))
        _, second, _ = run_cli("export-fsm", str(manifest_copy))

        assert first == second, "повторные запуски должны давать одинаковый вывод"

    def test_export_does_not_modify_manifest(self, run_cli, manifest_copy):
        """Выгрузка не меняет манифест.

        Команда только читает; изменение файла означало бы побочный эффект,
        который пользователь не запрашивал.
        """
        before = manifest_copy.read_text(encoding="utf-8")

        run_cli("export-fsm", str(manifest_copy))
        run_cli("export-fsm", str(manifest_copy), "--device", "light.kitchen")
        run_cli("export-fsm", str(manifest_copy), "--format", "graphviz")

        assert manifest_copy.read_text(encoding="utf-8") == before, "манифест не должен изменяться"
