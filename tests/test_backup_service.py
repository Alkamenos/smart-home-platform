"""Tests for BackupService."""

import tarfile
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from src.services.backup_service import BackupService


@pytest.fixture
def backup_service(tmp_path):
    """Create a BackupService instance with temp directory."""
    backup_dir = tmp_path / "backups"
    return BackupService(
        ha_url="http://localhost:8123",
        ha_token="test_token",
        backup_dir=backup_dir,
    )


@pytest.fixture
def sample_automation():
    """Sample automation data."""
    return {
        "id": "test_automation_1",
        "alias": "Test Automation",
        "trigger": [{"platform": "state", "entity_id": "binary_sensor.motion"}],
        "action": [{"service": "light.turn_on", "entity_id": "light.kitchen"}],
    }


@pytest.fixture
def sample_script():
    """Sample script data."""
    return {
        "alias": "Test Script",
        "sequence": [{"service": "light.toggle", "entity_id": "light.living_room"}],
    }


@pytest.fixture
def sample_scene():
    """Sample scene data."""
    return {
        "entity_id": "scene.living_room_evening",
        "name": "Living Room Evening",
    }


class TestBackupServiceInit:
    """Test BackupService initialization."""

    def test_default_values(self):
        """Test default initialization values."""
        service = BackupService()

        assert service.ha_url == "http://localhost:8123"
        assert service.ha_token is None
        assert service.backup_dir == Path("./backups")

    def test_custom_values(self, tmp_path):
        """Test custom initialization values."""
        backup_dir = tmp_path / "custom_backups"
        service = BackupService(
            ha_url="http://ha.local:8123",
            ha_token="my_token",
            backup_dir=backup_dir,
        )

        assert service.ha_url == "http://ha.local:8123"
        assert service.ha_token == "my_token"
        assert service.backup_dir == backup_dir

    def test_ha_url_trailing_slash_removed(self):
        """Test that trailing slash is removed from HA URL."""
        service = BackupService(ha_url="http://localhost:8123/")
        assert service.ha_url == "http://localhost:8123"


class TestBackupServiceSession:
    """Test session management."""

    @pytest.mark.asyncio
    async def test_get_session_creates_session(self, backup_service):
        """Test that _get_session creates a new session."""
        session = await backup_service._get_session()

        assert session is not None
        assert backup_service._session is session

    @pytest.mark.asyncio
    async def test_get_session_reuses_existing(self, backup_service):
        """Test that _get_session reuses existing session."""
        session1 = await backup_service._get_session()
        session2 = await backup_service._get_session()

        assert session1 is session2

    @pytest.mark.asyncio
    async def test_close_session(self, backup_service):
        """Test closing the session."""
        session = await backup_service._get_session()

        # Mock close to track calls
        session.close = AsyncMock()

        await backup_service.close()

        session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_without_session(self, backup_service):
        """Test closing when no session exists."""
        # Should not raise
        await backup_service.close()


class TestBackupServiceRequest:
    """Test API request handling."""

    @pytest.mark.asyncio
    async def test_request_success(self, backup_service):
        """Test successful API request."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"result": "success"})
        mock_response.text = AsyncMock(return_value="")

        mock_context_manager = AsyncMock()
        mock_context_manager.__aenter__.return_value = mock_response
        mock_context_manager.__aexit__.return_value = None

        mock_session = MagicMock()
        mock_session.request.return_value = mock_context_manager
        mock_session.closed = False

        with patch.object(backup_service, "_get_session", return_value=mock_session):
            result = await backup_service._request("GET", "/api/test")

            assert result == {"result": "success"}
            mock_session.request.assert_called_once_with("GET", "/api/test", json=None)

    @pytest.mark.asyncio
    async def test_request_no_content(self, backup_service):
        """Test request with 204 No Content response."""
        mock_response = MagicMock()
        mock_response.status = 204
        mock_response.text = AsyncMock(return_value="")

        mock_context_manager = AsyncMock()
        mock_context_manager.__aenter__.return_value = mock_response
        mock_context_manager.__aexit__.return_value = None

        mock_session = MagicMock()
        mock_session.request.return_value = mock_context_manager
        mock_session.closed = False

        with patch.object(backup_service, "_get_session", return_value=mock_session):
            result = await backup_service._request("DELETE", "/api/test")

            assert result is None

    @pytest.mark.asyncio
    async def test_request_error_status(self, backup_service):
        """Test request with error status code."""
        mock_response = MagicMock()
        mock_response.status = 500
        mock_response.text = AsyncMock(return_value="Internal Server Error")

        mock_context_manager = AsyncMock()
        mock_context_manager.__aenter__.return_value = mock_response
        mock_context_manager.__aexit__.return_value = None

        mock_session = MagicMock()
        mock_session.request.return_value = mock_context_manager
        mock_session.closed = False

        with (
            patch.object(backup_service, "_get_session", return_value=mock_session),
            pytest.raises(RuntimeError, match="HA API error: 500"),
        ):
            await backup_service._request("GET", "/api/test")

    @pytest.mark.asyncio
    async def test_request_connection_error(self, backup_service):
        """Test request with connection error."""
        import aiohttp

        mock_session = MagicMock()
        mock_session.request.side_effect = aiohttp.ClientError("Connection failed")
        mock_session.closed = False

        with (
            patch.object(backup_service, "_get_session", return_value=mock_session),
            pytest.raises(RuntimeError, match="Failed to connect"),
        ):
            await backup_service._request("GET", "/api/test")


class TestBackupServiceFetchData:
    """Test data fetching methods."""

    @pytest.mark.asyncio
    async def test_get_automations(self, backup_service):
        """Test fetching automations."""
        automations = [
            {"id": "auto1", "alias": "Automation 1"},
            {"id": "auto2", "alias": "Automation 2"},
        ]

        with patch.object(backup_service, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = automations

            result = await backup_service.get_automations()

            assert result == automations
            mock_request.assert_called_once_with("GET", "/api/config/automation/list")

    @pytest.mark.asyncio
    async def test_get_automations_empty(self, backup_service):
        """Test fetching empty automations list."""
        with patch.object(backup_service, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = []

            result = await backup_service.get_automations()

            assert result == []

    @pytest.mark.asyncio
    async def test_get_scripts(self, backup_service):
        """Test fetching scripts."""
        scripts = [{"alias": "Script 1"}, {"alias": "Script 2"}]

        with patch.object(backup_service, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = scripts

            result = await backup_service.get_scripts()

            assert result == scripts
            mock_request.assert_called_once_with("GET", "/api/config/script/list")

    @pytest.mark.asyncio
    async def test_get_scenes(self, backup_service):
        """Test fetching scenes."""
        scenes = [
            {"entity_id": "scene.scene1", "name": "Scene 1"},
            {"entity_id": "scene.scene2", "name": "Scene 2"},
        ]

        with patch.object(backup_service, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = scenes

            result = await backup_service.get_scenes()

            assert result == scenes
            mock_request.assert_called_once_with("GET", "/api/config/scene/list")

    @pytest.mark.asyncio
    async def test_get_config(self, backup_service):
        """Test fetching HA config."""
        config = {"latitude": 55.0, "longitude": 37.0, "elevation": 150}

        with patch.object(backup_service, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = config

            result = await backup_service.get_config()

            assert result == config
            mock_request.assert_called_once_with("GET", "/api/config")


class TestBackupServiceCreateBackup:
    """Test backup creation."""

    @pytest.mark.asyncio
    async def test_create_backup_success(self, backup_service, tmp_path):
        """Test successful backup creation."""
        with patch.object(backup_service, "get_automations", new_callable=AsyncMock) as mock_auto:
            mock_auto.return_value = []

            with patch.object(
                backup_service, "get_scripts", new_callable=AsyncMock
            ) as mock_scripts:
                mock_scripts.return_value = []

                with patch.object(
                    backup_service, "get_scenes", new_callable=AsyncMock
                ) as mock_scenes:
                    mock_scenes.return_value = []

                    backup_file = await backup_service.create_backup()

                    assert backup_file.exists()
                    assert backup_file.suffix == ".gz"
                    assert "ha_backup_" in backup_file.name

    @pytest.mark.asyncio
    async def test_create_backup_creates_directory(self, backup_service, tmp_path):
        """Test that backup directory is created if not exists."""
        backup_dir = tmp_path / "new_backups"
        backup_service.backup_dir = backup_dir

        assert not backup_dir.exists()

        with (
            patch.object(backup_service, "get_automations", new_callable=AsyncMock) as mock_auto,
            patch.object(backup_service, "get_scripts", new_callable=AsyncMock) as mock_scripts,
            patch.object(backup_service, "get_scenes", new_callable=AsyncMock) as mock_scenes,
        ):
            mock_auto.return_value = []
            mock_scripts.return_value = []
            mock_scenes.return_value = []

            await backup_service.create_backup()

            assert backup_dir.exists()

    @pytest.mark.asyncio
    async def test_create_backup_custom_name(self, backup_service):
        """Test backup with custom name."""
        with (
            patch.object(backup_service, "get_automations", new_callable=AsyncMock) as mock_auto,
            patch.object(backup_service, "get_scripts", new_callable=AsyncMock) as mock_scripts,
            patch.object(backup_service, "get_scenes", new_callable=AsyncMock) as mock_scenes,
        ):
            mock_auto.return_value = []
            mock_scripts.return_value = []
            mock_scenes.return_value = []

            backup_file = await backup_service.create_backup(backup_name="my_custom_backup")

            assert "my_custom_backup" in backup_file.name

    @pytest.mark.asyncio
    async def test_create_backup_selective_include(self, backup_service):
        """Test backup with selective includes."""
        with (
            patch.object(backup_service, "get_automations", new_callable=AsyncMock) as mock_auto,
            patch.object(backup_service, "get_scripts", new_callable=AsyncMock) as mock_scripts,
            patch.object(backup_service, "get_scenes", new_callable=AsyncMock) as mock_scenes,
            patch.object(backup_service, "get_config", new_callable=AsyncMock) as mock_config,
        ):
            mock_auto.return_value = [{"id": "auto1"}]
            mock_scripts.return_value = []
            mock_scenes.return_value = []
            mock_config.return_value = {}

            # Only include automations
            await backup_service.create_backup(
                include_automations=True,
                include_scripts=False,
                include_scenes=False,
                include_config=False,
            )

            mock_auto.assert_called_once()
            mock_scripts.assert_not_called()
            mock_scenes.assert_not_called()
            mock_config.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_backup_error(self, backup_service):
        """Test backup creation error handling."""
        with patch.object(backup_service, "get_automations", new_callable=AsyncMock) as mock_auto:
            mock_auto.side_effect = RuntimeError("API Error")

            with pytest.raises(RuntimeError, match="Failed to create backup"):
                await backup_service.create_backup()


class TestBackupServiceRestore:
    """Test backup restoration."""

    @pytest.mark.asyncio
    async def test_restore_backup_file_not_found(self, backup_service):
        """Test restore with non-existent file."""
        non_existent = Path("/non/existent/backup.tar.gz")

        with pytest.raises(FileNotFoundError):
            await backup_service.restore_backup(non_existent)

    @pytest.mark.asyncio
    async def test_restore_backup_dry_run(self, backup_service, tmp_path):
        """Test restore in dry-run mode."""
        # Create a simple backup file
        backup_file = tmp_path / "test_backup.tar.gz"
        yaml_file = tmp_path / "test_backup.yaml"

        backup_data = {
            "metadata": {"created_at": datetime.now().isoformat()},
            "automations": [{"id": "test_auto", "alias": "Test"}],
            "scripts": [],
            "scenes": [],
        }

        with open(yaml_file, "w") as f:
            yaml.dump(backup_data, f)

        with tarfile.open(backup_file, "w:gz") as tar:
            tar.add(yaml_file, arcname="test_backup.yaml")

        yaml_file.unlink()

        with patch.object(
            backup_service, "_restore_automations", new_callable=AsyncMock
        ) as mock_restore:
            mock_restore.return_value = {"count": 1, "failed": 0}

            result = await backup_service.restore_backup(backup_file, dry_run=True)

            assert result["success"] is True
            assert result["dry_run"] is True
            assert "automations: 1" in result["restored"]

    @pytest.mark.asyncio
    async def test_restore_automations(self, backup_service):
        """Test automation restoration."""
        automations = [
            {"id": "auto1", "alias": "Auto 1"},
            {"id": "auto2", "alias": "Auto 2"},
        ]

        # Mock _request to simulate API responses
        call_count = {"get": 0}

        async def mock_request(method, endpoint, data=None):
            if method == "GET":
                call_count["get"] += 1
                # First GET returns None (doesn't exist), second returns existing
                if call_count["get"] == 1:
                    return None
                else:
                    return {"id": "auto2"}
            else:
                # POST/PUT requests succeed
                return None

        with patch.object(backup_service, "_request", side_effect=mock_request):
            result = await backup_service._restore_automations(automations)

            assert result["count"] == 2
            assert result["failed"] == 0

    @pytest.mark.asyncio
    async def test_restore_automations_dry_run(self, backup_service, caplog):
        """Test automation restoration in dry-run mode."""
        import logging

        caplog.set_level(logging.INFO)

        automations = [{"id": "auto1", "alias": "Auto 1"}]

        result = await backup_service._restore_automations(automations, dry_run=True)

        assert result["count"] == 1
        assert result["failed"] == 0
        assert "[DRY RUN]" in caplog.text

    @pytest.mark.asyncio
    async def test_restore_scripts_dry_run(self, backup_service, caplog):
        """Test script restoration in dry-run mode."""
        import logging

        caplog.set_level(logging.INFO)

        scripts = [{"alias": "Script 1"}]

        result = await backup_service._restore_scripts(scripts, dry_run=True)

        assert result["count"] == 1
        assert result["failed"] == 0

    @pytest.mark.asyncio
    async def test_restore_scenes_dry_run(self, backup_service, caplog):
        """Test scene restoration in dry-run mode."""
        import logging

        caplog.set_level(logging.INFO)

        scenes = [{"entity_id": "scene.test", "name": "Test Scene"}]

        result = await backup_service._restore_scenes(scenes, dry_run=True)

        assert result["count"] == 1
        assert result["failed"] == 0


class TestBackupServiceListBackups:
    """Test backup listing."""

    def test_list_backups_empty(self, backup_service):
        """Test listing when no backups exist."""
        import asyncio

        async def run_test():
            backups = await backup_service.list_backups()
            assert backups == []

        asyncio.run(run_test())

    def test_list_backups_with_files(self, backup_service, tmp_path):
        """Test listing with existing backups."""
        import asyncio
        import time

        # Create backup files
        backup1 = backup_service.backup_dir / "backup1.tar.gz"
        backup2 = backup_service.backup_dir / "backup2.tar.gz"

        backup_service.backup_dir.mkdir(parents=True, exist_ok=True)
        backup1.touch()
        time.sleep(0.1)  # Ensure different timestamps
        backup2.touch()

        async def run_test():
            backups = await backup_service.list_backups()

            assert len(backups) == 2
            assert backups[0]["filename"] == "backup1.tar.gz"
            assert backups[1]["filename"] == "backup2.tar.gz"
            assert "size_bytes" in backups[0]
            assert "created_at" in backups[0]

        asyncio.run(run_test())


class TestBackupServiceDeleteBackup:
    """Test backup deletion."""

    def test_delete_backup_success(self, backup_service):
        """Test successful backup deletion."""
        import asyncio

        backup_service.backup_dir.mkdir(parents=True, exist_ok=True)
        backup_file = backup_service.backup_dir / "test.tar.gz"
        backup_file.touch()

        async def run_test():
            result = await backup_service.delete_backup(backup_file)
            assert result is True
            assert not backup_file.exists()

        asyncio.run(run_test())

    def test_delete_backup_not_found(self, backup_service):
        """Test deletion of non-existent file."""
        import asyncio

        non_existent = backup_service.backup_dir / "nonexistent.tar.gz"

        async def run_test():
            result = await backup_service.delete_backup(non_existent)
            assert result is False

        asyncio.run(run_test())


class TestBackupServiceValidate:
    """Test backup validation."""

    def test_validate_backup_nonexistent(self, backup_service):
        """Test validation of non-existent file."""
        import asyncio

        non_existent = Path("/non/existent.tar.gz")

        async def run_test():
            result = await backup_service.validate_backup(non_existent)

            assert result["valid"] is False
            assert "Backup file does not exist" in result["errors"]

        asyncio.run(run_test())

    def test_validate_backup_valid(self, backup_service, tmp_path):
        """Test validation of valid backup."""
        import asyncio

        # Create valid backup
        backup_file = tmp_path / "valid.tar.gz"
        yaml_file = tmp_path / "valid.yaml"

        backup_data = {
            "metadata": {},
            "automations": [{"id": "auto1"}],
            "scripts": [{"alias": "script1"}],
            "scenes": [{"entity_id": "scene.scene1"}],
        }

        with open(yaml_file, "w") as f:
            yaml.dump(backup_data, f)

        with tarfile.open(backup_file, "w:gz") as tar:
            tar.add(yaml_file, arcname="valid.yaml")

        yaml_file.unlink()

        async def run_test():
            result = await backup_service.validate_backup(backup_file)

            assert result["valid"] is True
            assert result["errors"] == []
            assert result["info"]["has_automations"] is True
            assert result["info"]["has_scripts"] is True
            assert result["info"]["has_scenes"] is True
            assert result["info"]["automation_count"] == 1

        asyncio.run(run_test())

    def test_validate_backup_invalid_archive(self, backup_service, tmp_path):
        """Test validation of invalid archive."""
        import asyncio

        # Create invalid file
        invalid_file = tmp_path / "invalid.tar.gz"
        invalid_file.write_text("not a tar.gz file")

        async def run_test():
            result = await backup_service.validate_backup(invalid_file)

            assert result["valid"] is False
            assert any("Invalid archive" in err for err in result["errors"])

        asyncio.run(run_test())
