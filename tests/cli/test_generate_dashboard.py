"""Тесты команды `generate-dashboard` (BACKLOG B8, enhancement 19).

Команда выгружает дашборд Home Assistant из манифеста дома — тот же, что
отдаёт `GET /api/v1/system/dashboard`, но без запущенной платформы и без
записи в дом. Нужна, чтобы панель можно было собрать и положить в git или
передать владельцу файлом.

Все тесты идут через штатную точку входа `smart_home.cli.main.main()`, а не
через внутренние функции: проверяются разбор аргументов и код возврата — то,
где команда ломается у пользователя.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def _dashboard(text: str) -> dict[str, Any]:
    """Разобрать YAML дашборда из вывода команды.

    Args:
        text: Текст, напечатанный командой.

    Returns:
        Конфигурация Lovelace.
    """
    data = yaml.safe_load(text)
    assert isinstance(data, dict), f"ожидался словарь дашборда: {text[:300]}"
    return data


class TestSuccessfulExport:
    """Успешная выгрузка дашборда."""

    def test_prints_dashboard_to_stdout(self, run_cli, manifest_copy) -> None:
        """Без `--output` дашборд печатается целиком."""
        code, out, err = run_cli("generate-dashboard", str(manifest_copy))

        assert code == 0, f"ожидался 0, получено {code}: {err}"
        dashboard = _dashboard(out)
        assert dashboard.get("views"), "в дашборде нет ни одного представления"
        assert dashboard.get("title"), "у дашборда нет названия"

    def test_writes_to_file_when_output_given(self, run_cli, manifest_copy, tmp_path) -> None:
        """С `--output` дашборд пишется в файл, а не печатается."""
        target = tmp_path / "lovelace_platform.yaml"

        code, out, _ = run_cli("generate-dashboard", str(manifest_copy), "--output", str(target))

        assert code == 0, out
        assert target.exists(), "файл дашборда должен быть создан"
        dashboard = _dashboard(target.read_text(encoding="utf-8"))
        assert dashboard.get("views"), "в файле нет представлений"

    def test_creates_missing_parent_directories(self, run_cli, manifest_copy, tmp_path) -> None:
        """Отсутствующие каталоги создаются — иначе команда падает на вводе пути."""
        target = tmp_path / "a" / "b" / "lovelace.yaml"

        code, out, _ = run_cli("generate-dashboard", str(manifest_copy), "-o", str(target))

        assert code == 0, out
        assert target.exists(), "вложенные каталоги должны быть созданы"

    def test_reports_destination_and_counts(self, run_cli, manifest_copy, tmp_path) -> None:
        """Пользователю сообщается, куда записано и сколько получилось."""
        target = tmp_path / "lovelace.yaml"

        _, out, _ = run_cli("generate-dashboard", str(manifest_copy), "-o", str(target))

        assert str(target) in out, f"путь должен быть назван: {out}"
        assert "представлен" in out, f"ожидался счёт представлений: {out}"
        assert "карточ" in out, f"ожидался счёт карточек: {out}"

    def test_output_is_ready_for_home_assistant(self, run_cli, manifest_copy) -> None:
        """Типы карточек — только те, что Home Assistant знает (B79)."""
        _, out, _ = run_cli("generate-dashboard", str(manifest_copy))

        dashboard = _dashboard(out)
        allowed = {"entities", "markdown"}
        for view in dashboard["views"]:
            for card in view.get("cards") or []:
                assert card.get("type") in allowed, (
                    f"карточка неизвестного типа {card.get('type')!r}: "
                    f"Home Assistant покажет «ошибка конфигурации»"
                )


class TestTitleFallback:
    """Пустое название заменяется именем дома."""

    def test_empty_title_becomes_the_house_name(self, run_cli, manifest_copy, tmp_path) -> None:
        """В списке панелей дашборд должен называться домом, а не пустой строкой."""
        data = yaml.safe_load(manifest_copy.read_text(encoding="utf-8"))
        house_name = data["instance"]["name"]
        data.setdefault("dashboard", {})["title"] = ""
        edited = tmp_path / "manifest_no_title.yaml"
        edited.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        _, out, err = run_cli("generate-dashboard", str(edited))

        assert err == "", err
        assert _dashboard(out)["title"] == house_name


class TestFailuresAreNamed:
    """Ошибки объясняются, а не молчат."""

    def test_missing_manifest_is_reported(self, run_cli, tmp_path) -> None:
        """Несуществующий файл — код 1 и понятное сообщение."""
        code, _, err = run_cli("generate-dashboard", str(tmp_path / "nope.yaml"))

        assert code == 1
        assert "не найден" in err.lower() or "not found" in err.lower(), err

    def test_broken_yaml_is_reported(self, run_cli, tmp_path) -> None:
        """Битый YAML не должен выглядеть как пустой дашборд."""
        broken = tmp_path / "broken.yaml"
        broken.write_text("rooms: [", encoding="utf-8")

        code, _, err = run_cli("generate-dashboard", str(broken))

        assert code == 1
        assert "YAML" in err or "yaml" in err, err

    def test_empty_house_is_reported(self, run_cli, tmp_path) -> None:
        """Манифест без мест — не дашборд, а ошибка."""
        empty = tmp_path / "empty.yaml"
        empty.write_text(
            yaml.safe_dump(
                {
                    "version": 1,
                    "instance": {
                        "id": "probe",
                        "name": "Probe",
                        "owner": "probe",
                        "created_at": "2026-01-01T00:00:00Z",
                    },
                    "rooms": [],
                },
                allow_unicode=True,
            ),
            encoding="utf-8",
        )

        code, out, err = run_cli("generate-dashboard", str(empty))

        assert code == 1, f"пустой дом не должен давать дашборд: {out}"
        assert "комнат" in err.lower() or "локаций" in err.lower(), err


class TestDefaultManifest:
    """Манифест можно не указывать — берётся эталон боевого дома."""

    def test_uses_reference_manifest_by_default(self, run_cli) -> None:
        """Без аргумента команда читает эталонный манифест из репозитория."""
        reference = Path("instances/leonids_house_prod/manifest.yaml")
        assert reference.exists(), "эталонный манифест пропал из репозитория"

        code, out, err = run_cli("generate-dashboard")

        assert code == 0, err
        assert _dashboard(out)["views"]
