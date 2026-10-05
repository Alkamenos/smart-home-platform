"""Резервная копия должна быть сжатой, проверяемой и восстановимой.

Блокер 3-бис продакшен-плана: «регулярный `tar`/`zstd` тома `data/` +
`manifest.yaml` во внешнее хранилище с проверкой целостности и тестом
восстановления».

Что проверено здесь
-------------------
Проверяется то, что можно доказать локально:

- копия содержит **всё**, без чего платформа не восстановится: манифест,
  состояния автоматов, источники данных и **файл ключа шифрования**;
- целостность проверяется, а повреждённый архив обнаруживается;
- восстановление из архива действительно возвращает данные, а не «отчитывается
  об успехе»;
- ротация ограничивает число копий, иначе бэкапы съедят диск.

Что здесь НЕ проверяется
------------------------
Выгрузка во внешнее хранилище. Путь назначения задаётся переменной
`BACKUP_DEST_DIR`, и в тесте он указывает во временный каталог. Проверить
потерю хоста или диска здесь нельзя — для этого нужна инфраструктура, которой
нет. Соответственно, скрипт не имеет права считать задачу выполненной, пока
назначение не настроено: см. проверку `test_default_destination_is_same_host`.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

import os
import subprocess
import tarfile
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEPLOY_SH = REPO_ROOT / "deploy" / "scripts" / "deploy.sh"


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch) -> Path:
    """Изолированное развёртывание: свои config, data и каталог копий."""
    compose_dir = tmp_path / "docker"
    (compose_dir / "config").mkdir(parents=True)
    (compose_dir / "data").mkdir(parents=True)
    (compose_dir / "backups").mkdir()

    (compose_dir / "config" / "manifest.yaml").write_text(
        "rooms:\n  - id: kitchen\n", encoding="utf-8"
    )
    (compose_dir / "data" / "state.json").write_text(
        '{"light.kitchen": {"state": "ON"}}', encoding="utf-8"
    )
    (compose_dir / "data" / "sources.json").write_text(
        '{"src-1": {"token": "encrypted"}}', encoding="utf-8"
    )
    (compose_dir / "data" / "encryption.key").write_text("key-material", encoding="utf-8")

    monkeypatch.setenv("DOCKER_COMPOSE_FILE", str(compose_dir / "docker-compose.prod.yml"))
    monkeypatch.setenv("BACKUP_DEST_DIR", str(compose_dir / "external"))
    return compose_dir


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Запустить deploy.sh с нужными аргументами."""
    env = {**os.environ, "BACKUP_SKIP_COMPOSE": "1"}
    result = subprocess.run(
        ["bash", str(DEPLOY_SH), *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
        check=False,
        timeout=120,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"deploy.sh {' '.join(args)} завершился с {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result


def _archives(sandbox: Path) -> list[Path]:
    return sorted((sandbox / "external").glob("*.tar.gz"))


class TestBackupContainsEverythingNeededToRestore:
    """Копия без любого из этих файлов восстановления не даёт."""

    def test_archive_is_created(self, sandbox: Path) -> None:
        """Архив появляется в каталоге назначения."""
        _run("backup")

        assert _archives(sandbox), f"архив не создан в {sandbox / 'external'}"

    def test_archive_holds_manifest_and_data(self, sandbox: Path) -> None:
        """Внутри есть манифест, состояния и источники."""
        _run("backup")

        with tarfile.open(_archives(sandbox)[-1]) as archive:
            names = set(archive.getnames())

        for expected in (
            "config/manifest.yaml",
            "data/state.json",
            "data/sources.json",
        ):
            assert expected in names, f"в архиве нет {expected}: {sorted(names)}"

    def test_archive_holds_encryption_key(self, sandbox: Path) -> None:
        """Файл ключа шифрования попадает в архив.

        Без него сохранённые токены Home Assistant не расшифровать, то есть
        восстановление формально произойдёт, а платформа останется нерабочей.
        """
        _run("backup")

        with tarfile.open(_archives(sandbox)[-1]) as archive:
            names = set(archive.getnames())

        assert any(n.endswith("encryption.key") for n in names), (
            f"файла ключа нет в архиве: {sorted(names)}"
        )

    def test_archive_holds_checksums(self, sandbox: Path) -> None:
        """В архиве есть файл сумм для проверки целостности."""
        _run("backup")

        with tarfile.open(_archives(sandbox)[-1]) as archive:
            names = set(archive.getnames())

        assert any("SHA256SUMS" in n for n in names), f"файла сумм нет в архиве: {sorted(names)}"


class TestIntegrityVerification:
    """Повреждение копии должно обнаруживаться, а не оставаться незамеченным."""

    def test_verify_passes_for_fresh_archive(self, sandbox: Path) -> None:
        """Свежая копия проходит проверку."""
        _run("backup")

        result = _run("verify")

        assert result.returncode == 0

    def test_verify_detects_corrupted_archive(self, sandbox: Path) -> None:
        """Испорченная копия обнаруживается."""
        _run("backup")
        archive = _archives(sandbox)[-1]
        archive.write_bytes(archive.read_bytes()[: len(archive.read_bytes()) // 2])

        result = _run("verify", check=False)

        assert result.returncode != 0, (
            "испорченный архив прошёл проверку: целостность не контролируется"
        )

    def test_restore_refuses_corrupted_archive(self, sandbox: Path) -> None:
        """Восстановление не должно молча раскладывать мусор на место."""
        _run("backup")
        archive = _archives(sandbox)[-1]
        archive.write_bytes(archive.read_bytes()[: len(archive.read_bytes()) // 2])

        result = _run("restore", str(archive), check=False)

        assert result.returncode != 0, (
            "восстановление из повреждённого архива выполнилось: данные на месте "
            "оказались бы битыми"
        )

    def test_restore_refuses_tampered_archive_that_unpacks_fine(self, sandbox: Path) -> None:
        """Копия с подменённым содержимым отвергается, даже если распаковывается.

        Различие существенно. Обрезанный архив отвергается самой распаковкой, и
        его проверяет любой отказ `tar`. Настоящая угроза — копия, которая
        **открывается**, но содержит другие данные: рассинхронизация, битый
        сектор, ручная правка. Её ловит только сверка сумм, поэтому отказ
        `restore` здесь и означает отказ по проверке целостности.
        """
        _run("backup")
        original = _archives(sandbox)[-1]
        tampered = sandbox / "external" / "backup_tampered.tar.gz"

        work = sandbox.parent / "tamper_work"
        work.mkdir(exist_ok=True)
        with tarfile.open(original) as src:
            src.extractall(work, filter="data")

        # Подменяем данные, но оставляем SHA256SUMS от оригинала.
        (work / "data" / "state.json").write_text('{"подменено": true}', encoding="utf-8")
        with tarfile.open(tampered, "w:gz") as dst:
            for name in ("config", "data", "SHA256SUMS"):
                dst.add(work / name, arcname=name)

        assert tarfile.is_tarfile(tampered), "подделанный архив должен открываться"

        (sandbox / "data" / "state.json").write_text("текущее", encoding="utf-8")
        result = _run("restore", str(tampered), check=False)

        assert result.returncode != 0, (
            "подменённая копия восстановлена: на месте оказались данные, "
            "которые никогда не бэкапились"
        )
        assert (sandbox / "data" / "state.json").read_text(encoding="utf-8") == "текущее", (
            "файл данных изменён, хотя восстановление должно было быть отменено"
        )


class TestRestoreActuallyRestores:
    """Главное свойство: после восстановления данные на месте."""

    def test_restore_returns_lost_files(self, sandbox: Path) -> None:
        """Удалённые файлы возвращаются из архива."""
        _run("backup")

        (sandbox / "data" / "state.json").unlink()
        (sandbox / "config" / "manifest.yaml").unlink()
        assert not (sandbox / "data" / "state.json").exists()

        _run("restore", str(_archives(sandbox)[-1]))

        assert (sandbox / "data" / "state.json").read_text(encoding="utf-8") == (
            '{"light.kitchen": {"state": "ON"}}'
        ), "состояния не восстановлены"
        assert (sandbox / "config" / "manifest.yaml").read_text(encoding="utf-8") == (
            "rooms:\n  - id: kitchen\n"
        ), "манифест не восстановлен"

    def test_restore_returns_key_file(self, sandbox: Path) -> None:
        """Файл ключа восстанавливается вместе с данными."""
        _run("backup")
        (sandbox / "data" / "encryption.key").unlink()

        _run("restore", str(_archives(sandbox)[-1]))

        assert (sandbox / "data" / "encryption.key").read_text(
            encoding="utf-8"
        ) == "key-material", "файл ключа не восстановлен: токены останутся нерасшифровываемыми"

    def test_restore_keeps_newer_backup_of_current_state(self, sandbox: Path) -> None:
        """Перед восстановлением текущие данные сохраняются отдельно.

        Восстановление затирает каталоги, поэтому без копии «до» операция
        необратима: восстановиться будет уже не из чего.
        """
        _run("backup")
        archive = _archives(sandbox)[-1]
        (sandbox / "data" / "state.json").write_text('{"light.kitchen": "МУСОР"}', encoding="utf-8")

        _run("restore", str(archive))

        safety_dirs = list((sandbox / "backups").glob("pre_restore_*"))
        assert safety_dirs, "текущие данные не сохранены перед восстановлением"
        assert (safety_dirs[0] / "data" / "state.json").read_text(encoding="utf-8") == (
            '{"light.kitchen": "МУСОР"}'
        ), "сохранён не тот файл, который был на месте"


class TestRetention:
    """Без ротации бэкапы съедают диск."""

    def test_old_archives_are_pruned(self, sandbox: Path) -> None:
        """Число копий ограничено настройкой."""
        os.environ["BACKUP_KEEP"] = "2"
        try:
            for _ in range(4):
                _run("backup")
        finally:
            os.environ.pop("BACKUP_KEEP", None)

        assert len(_archives(sandbox)) <= 2, (
            f"ротация не работает: копий {len(_archives(sandbox))} при лимите 2"
        )

    def test_newest_archive_is_kept(self, sandbox: Path) -> None:
        """Ротация не выбрасывает последнюю копию."""
        os.environ["BACKUP_KEEP"] = "1"
        try:
            for _ in range(3):
                _run("backup")
        finally:
            os.environ.pop("BACKUP_KEEP", None)

        archives = _archives(sandbox)
        assert len(archives) == 1
        with tarfile.open(archives[0]) as archive:
            assert "data/state.json" in archive.getnames(), "оставшаяся копия пуста"


class TestScriptNeverTouchesRealDeployment:
    """Тесты и проверки не должны писать в боевое развёртывание.

    Случилось при разработке этих тестов: `DOCKER_COMPOSE_FILE` был зашит
    литералом, поэтому песочница из временного каталога не действовала, тесты
    проходили, а `restore` раскладывал данные по настоящим каталогам
    `deploy/docker/`. Каталоги уцелели только потому, что копия снималась с
    того же места, откуда и раскладывалась.

    Поэтому проверка обязана быть явной: скрипт обязан уважать
    `DOCKER_COMPOSE_FILE` из окружения, иначе любая его проверка рискует
    испортить боевые данные молча.
    """

    def test_compose_path_comes_from_environment(self, sandbox: Path) -> None:
        """Копия уходит в каталог, заданный окружением, а не в репозиторий."""
        _run("backup")

        assert _archives(sandbox), "архив создан не в песочнице"

    def test_repository_deployment_is_left_untouched(self, sandbox: Path) -> None:
        """Каталоги настоящего развёртывания не меняются.

        Снимки до и после сравниваются по содержимому: одной проверки «файлы не
        исчезли» мало, скрипт мог бы перезаписать их тем же содержимым и тест
        прошёл бы.
        """
        real_config = REPO_ROOT / "deploy" / "docker" / "config"
        real_data = REPO_ROOT / "deploy" / "docker" / "data"

        before = {
            path: path.read_bytes() for path in sorted(real_config.glob("*")) if path.is_file()
        }
        before_data = {
            path: path.read_bytes() for path in sorted(real_data.glob("*")) if path.is_file()
        }

        _run("backup")
        _run("restore", str(_archives(sandbox)[-1]))

        after = {
            path: path.read_bytes() for path in sorted(real_config.glob("*")) if path.is_file()
        }
        after_data = {
            path: path.read_bytes() for path in sorted(real_data.glob("*")) if path.is_file()
        }

        assert after == before, (
            f"боевая конфигурация изменена проверкой: было {sorted(before)}, стало {sorted(after)}"
        )
        assert after_data == before_data, (
            f"боевые данные изменены проверкой: было {sorted(before_data)}, "
            f"стало {sorted(after_data)}"
        )

    def test_script_honours_compose_file_variable(self) -> None:
        """В скрипте нет зашитого пути к compose-файлу.

        Проверка по тексту, а не по поведению: иначе подмена пути на константу,
        совпадающую с тестовой, осталась бы незамеченной.
        """
        source = DEPLOY_SH.read_text(encoding="utf-8")

        assert "DOCKER_COMPOSE_FILE:-" in source, (
            "путь к compose-файлу задан литералом: скрипт нельзя направить в "
            "другое окружение, и любая его проверка пишет в боевые каталоги"
        )


class TestDestinationIsHonest:
    """Назначение по умолчанию не должно выдавать себя за внешнее хранилище."""

    def test_default_destination_is_same_host(self, sandbox: Path) -> None:
        """Без явного `BACKUP_DEST_DIR` копия остаётся на том же хосте.

        Так и должно быть по умолчанию, но скрипт обязан **предупредить**: иначе
        бэкап выглядит защитой от потери, а от потери диска не спасает.
        """
        os.environ.pop("BACKUP_DEST_DIR", None)
        try:
            result = _run("backup")
        finally:
            os.environ["BACKUP_DEST_DIR"] = str(sandbox / "external")

        assert _archives(sandbox.parent / "docker" / "backups") or (sandbox / "backups").exists(), (
            "копия создана не там"
        )
        combined = (result.stdout + result.stderr).lower()
        assert any(word in combined for word in ("внешн", "same host", "том же хосте")), (
            "копия создана рядом с данными без предупреждения о том, что это не "
            f"защита от потери диска:\n{result.stdout}"
        )
