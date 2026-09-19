"""
Tests for Secrets Management Module.

Tests cover:
- Environment variable resolution with ${VAR} syntax
- Default values support
- Nested dictionary/list resolution
- Plain-text secret validation
- .env file loading
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

import os
from pathlib import Path
from typing import Any

import pytest
from src.core.secrets import (
    SecretsResolver,
    get_resolver,
    resolve_secrets,
    validate_secrets,
)


class TestSecretsResolverInitialization:
    """Test SecretsResolver initialization."""

    def test_init_default(self) -> None:
        """Test default initialization."""
        resolver = SecretsResolver(load_dotenv=False)
        assert resolver is not None
        assert resolver.PATTERN is not None

    def test_init_with_env_file(self, tmp_path: Path) -> None:
        """Test initialization with custom .env file."""
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_VAR=test_value\n")

        resolver = SecretsResolver(env_file=env_file, load_dotenv=True)
        assert resolver is not None


class TestSecretsResolverResolve:
    """Test environment variable resolution."""

    def test_resolve_simple_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test resolving a simple environment variable."""
        monkeypatch.setenv("TEST_TOKEN", "secret123")
        resolver = SecretsResolver(load_dotenv=False)

        result = resolver.resolve("${TEST_TOKEN}")
        assert result == "secret123"

    def test_resolve_with_default(self) -> None:
        """Test resolving with default value."""
        resolver = SecretsResolver(load_dotenv=False)

        # Remove any existing variable
        if "NONEXISTENT_VAR_12345" in os.environ:
            del os.environ["NONEXISTENT_VAR_12345"]

        result = resolver.resolve("${NONEXISTENT_VAR_12345:default_value}")
        assert result == "default_value"

    def test_resolve_missing_var_no_default(self) -> None:
        """Test that missing variable without default raises error."""
        resolver = SecretsResolver(load_dotenv=False)

        # Remove any existing variable
        if "MISSING_VAR_67890" in os.environ:
            del os.environ["MISSING_VAR_67890"]

        with pytest.raises(ValueError, match="MISSING_VAR_67890"):
            resolver.resolve("${MISSING_VAR_67890}")

    def test_resolve_multiple_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test resolving multiple variables in one string."""
        monkeypatch.setenv("USER", "admin")
        monkeypatch.setenv("PASS", "password123")
        resolver = SecretsResolver(load_dotenv=False)

        result = resolver.resolve("${USER}:${PASS}")
        assert result == "admin:password123"

    def test_resolve_mixed_content(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test resolving variables mixed with static content."""
        monkeypatch.setenv("HOST", "localhost")
        resolver = SecretsResolver(load_dotenv=False)

        result = resolver.resolve("http://${HOST}:8080/api")
        assert result == "http://localhost:8080/api"

    def test_resolve_no_pattern(self) -> None:
        """Test string without pattern returns unchanged."""
        resolver = SecretsResolver(load_dotenv=False)

        result = resolver.resolve("plain_text_string")
        assert result == "plain_text_string"

    def test_resolve_non_string(self) -> None:
        """Test non-string values return unchanged."""
        resolver = SecretsResolver(load_dotenv=False)

        assert resolver.resolve(123) == 123  # type: ignore[arg-type,comparison-overlap]
        assert resolver.resolve(None) is None  # type: ignore[arg-type]
        assert resolver.resolve(True) is True  # type: ignore[arg-type,comparison-overlap]


class TestSecretsResolverDict:
    """Test dictionary resolution."""

    def test_resolve_flat_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test resolving flat dictionary."""
        monkeypatch.setenv("TOKEN", "abc123")
        monkeypatch.setenv("URL", "https://api.example.com")
        resolver = SecretsResolver(load_dotenv=False)

        data: dict[str, Any] = {"token": "${TOKEN}", "url": "${URL}", "name": "static_value"}

        result = resolver.resolve_dict(data)
        assert result["token"] == "abc123"
        assert result["url"] == "https://api.example.com"
        assert result["name"] == "static_value"

    def test_resolve_nested_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test resolving nested dictionary."""
        monkeypatch.setenv("API_KEY", "xyz789")
        resolver = SecretsResolver(load_dotenv=False)

        data: dict[str, Any] = {
            "adapter": {
                "mode": "websocket",
                "token": "${API_KEY}",
                "config": {"timeout": "${TIMEOUT:30}"},
            }
        }

        result = resolver.resolve_dict(data)
        assert result["adapter"]["token"] == "xyz789"
        assert result["adapter"]["config"]["timeout"] == "30"

    def test_resolve_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test resolving list with environment variables."""
        monkeypatch.setenv("ITEM1", "first")
        monkeypatch.setenv("ITEM2", "second")
        resolver = SecretsResolver(load_dotenv=False)

        data: dict[str, Any] = {"items": ["${ITEM1}", "${ITEM2}", "static"]}

        result = resolver.resolve_dict(data)
        assert result["items"] == ["first", "second", "static"]

    def test_resolve_tuple(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test resolving tuple with environment variables."""
        monkeypatch.setenv("VAL1", "v1")
        monkeypatch.setenv("VAL2", "v2")
        resolver = SecretsResolver(load_dotenv=False)

        data: dict[str, Any] = {"coords": ("${VAL1}", "${VAL2}")}

        result = resolver.resolve_dict(data)
        assert result["coords"] == ("v1", "v2")


class TestSecretsResolverPattern:
    """Test secret pattern detection."""

    def test_is_secret_pattern_true(self) -> None:
        """Test detecting secret patterns."""
        resolver = SecretsResolver(load_dotenv=False)

        assert resolver.is_secret_pattern("${TOKEN}") is True
        assert resolver.is_secret_pattern("${API_KEY:default}") is True
        assert resolver.is_secret_pattern("prefix_${VAR}_suffix") is True

    def test_is_secret_pattern_false(self) -> None:
        """Test non-secret patterns."""
        resolver = SecretsResolver(load_dotenv=False)

        assert resolver.is_secret_pattern("plain_text") is False
        assert resolver.is_secret_pattern("$VAR") is False
        assert resolver.is_secret_pattern("${VAR") is False
        assert resolver.is_secret_pattern("VAR}") is False


class TestSecretsResolverValidation:
    """Test plain-text secret validation."""

    def test_validate_no_secrets(self) -> None:
        """Test validation passes when no secrets present."""
        resolver = SecretsResolver(load_dotenv=False)

        data: dict[str, Any] = {"name": "test", "value": 123}

        errors = resolver.validate_no_plain_secrets(data)
        assert len(errors) == 0

    def test_validate_with_pattern_secrets(self) -> None:
        """Test validation passes when secrets use pattern syntax."""
        resolver = SecretsResolver(load_dotenv=False)

        data: dict[str, Any] = {"adapter": {"token": "${HA_TOKEN}", "password": "${DB_PASSWORD}"}}

        errors = resolver.validate_no_plain_secrets(data)
        assert len(errors) == 0

    def test_validate_detects_plain_token(self) -> None:
        """Test validation detects plain-text token."""
        resolver = SecretsResolver(load_dotenv=False)

        data: dict[str, Any] = {"adapter": {"token": "super_secret_token_123"}}

        errors = resolver.validate_no_plain_secrets(data)
        assert len(errors) == 1
        assert "Plain-text secret detected" in errors[0]
        assert "token" in errors[0]

    def test_validate_detects_plain_password(self) -> None:
        """Test validation detects plain-text password."""
        resolver = SecretsResolver(load_dotenv=False)

        data: dict[str, Any] = {"database": {"password": "my_secret_password"}}

        errors = resolver.validate_no_plain_secrets(data)
        assert len(errors) == 1
        assert "password" in errors[0]

    def test_validate_allows_placeholders(self) -> None:
        """Test validation allows placeholder values."""
        resolver = SecretsResolver(load_dotenv=False)

        data: dict[str, Any] = {"token": "changeme", "password": "your_token_here", "secret": "xxx"}

        errors = resolver.validate_no_plain_secrets(data)
        assert len(errors) == 0

    def test_validate_nested_structure(self) -> None:
        """Test validation in nested structures."""
        resolver = SecretsResolver(load_dotenv=False)

        data: dict[str, Any] = {"level1": {"level2": {"api_key": "real_api_key_12345"}}}

        errors = resolver.validate_no_plain_secrets(data)
        assert len(errors) == 1
        assert "level1.level2.api_key" in errors[0]

    def test_validate_custom_secret_keys(self) -> None:
        """Test validation with custom secret key names."""
        resolver = SecretsResolver(load_dotenv=False)

        data: dict[str, Any] = {"custom_secret": "should_be_detected"}

        errors = resolver.validate_no_plain_secrets(data, secret_keys=["custom_secret"])
        assert len(errors) == 1


class TestSecretsResolverEnvFile:
    """Test .env file loading."""

    def test_load_env_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test loading environment from .env file."""
        pytest.importorskip("dotenv")  # <--- Тест скипнется, если библиотеки нет
        # Create .env file first
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_ENV_VAR=loaded_from_file\n")

        # Clear any existing variable and create resolver without auto-loading
        monkeypatch.delenv("TEST_ENV_VAR", raising=False)
        if "TEST_ENV_VAR" in os.environ:
            del os.environ["TEST_ENV_VAR"]

        # Create resolver without auto-loading, then load manually
        resolver = SecretsResolver(env_file=env_file, load_dotenv=False)
        resolver._load_env_file()  # Explicitly load after file exists

        result = resolver.resolve("${TEST_ENV_VAR}")
        assert result == "loaded_from_file"

    def test_load_env_file_explicit_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytest.importorskip("dotenv")  # <--- Тест скипнется, если библиотеки нет
        """Test loading environment from explicit .env file path."""
        # Create .env file first
        env_file = tmp_path / "custom.env"
        env_file.write_text("EXPLICIT_VAR=explicit_value\n")

        # Clear any existing variable
        monkeypatch.delenv("EXPLICIT_VAR", raising=False)
        if "EXPLICIT_VAR" in os.environ:
            del os.environ["EXPLICIT_VAR"]

        # Create resolver without auto-loading, then load manually
        resolver = SecretsResolver(env_file=env_file, load_dotenv=False)
        resolver._load_env_file()  # Explicitly load after file exists

        result = resolver.resolve("${EXPLICIT_VAR}")
        assert result == "explicit_value"


class TestGlobalFunctions:
    """Test global convenience functions."""

    def test_get_resolver_singleton(self) -> None:
        """Test that get_resolver returns singleton."""
        resolver1 = get_resolver()
        resolver2 = get_resolver()
        assert resolver1 is resolver2

    def test_resolve_secrets_function(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test resolve_secrets convenience function."""
        monkeypatch.setenv("GLOBAL_TOKEN", "global123")

        # Reset global resolver
        import src.core.secrets as secrets_module

        secrets_module._resolver = None

        data: dict[str, Any] = {"token": "${GLOBAL_TOKEN}"}
        result = resolve_secrets(data)
        assert result["token"] == "global123"

    def test_validate_secrets_function(self) -> None:
        """Test validate_secrets convenience function."""
        # Reset global resolver
        import src.core.secrets as secrets_module

        secrets_module._resolver = None

        data: dict[str, Any] = {"password": "plain_password"}
        errors = validate_secrets(data)
        assert len(errors) == 1


class TestSecretsResolverEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_string(self) -> None:
        """Test resolving empty string."""
        resolver = SecretsResolver(load_dotenv=False)
        result = resolver.resolve("")
        assert result == ""

    def test_dollar_without_braces(self) -> None:
        """Test dollar sign without braces is not replaced."""
        resolver = SecretsResolver(load_dotenv=False)
        result = resolver.resolve("$100 price")
        assert result == "$100 price"

    def test_incomplete_pattern(self) -> None:
        """Test incomplete pattern is not replaced."""
        resolver = SecretsResolver(load_dotenv=False)
        result = resolver.resolve("${INCOMPLETE")
        assert result == "${INCOMPLETE"

    def test_complex_nested_structure(self) -> None:
        """Test complex nested structure with lists and dicts."""
        import os

        os.environ["COMPLEX_VAL"] = "complex_value"

        resolver = SecretsResolver(load_dotenv=False)

        data: dict[str, Any] = {
            "config": {
                "servers": [
                    {"host": "${COMPLEX_VAL}", "port": 80},
                    {"host": "static_host", "port": 443},
                ],
                "enabled": True,
            }
        }

        result = resolver.resolve_dict(data)
        assert result["config"]["servers"][0]["host"] == "complex_value"
        assert result["config"]["servers"][1]["host"] == "static_host"
        assert result["config"]["enabled"] is True

    def test_validation_empty_dict(self) -> None:
        """Test validation on empty dictionary."""
        resolver = SecretsResolver(load_dotenv=False)
        errors = resolver.validate_no_plain_secrets({})
        assert len(errors) == 0

    def test_validation_list_of_dicts(self) -> None:
        """Test validation on list of dictionaries."""
        resolver = SecretsResolver(load_dotenv=False)

        data: dict[str, Any] = {"items": [{"token": "secret1"}, {"token": "${TOKEN_VAR}"}]}

        errors = resolver.validate_no_plain_secrets(data)
        assert len(errors) == 1
        assert "items[0].token" in errors[0]
