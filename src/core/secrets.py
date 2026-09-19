"""
Secrets Management Module.

Provides secure handling of sensitive data such as tokens, passwords,
and API keys through environment variable substitution.

Features:
- Environment variable resolution with ${VAR_NAME} syntax
- Optional .env file support via python-dotenv
- Validation to prevent plain-text secrets in manifests
- Integration with manifest loader
"""

import os
import re
from pathlib import Path
from typing import Any

from loguru import logger


class SecretsResolver:
    """
    Resolves secret values from environment variables.

    Supports syntax: ${VAR_NAME} or ${VAR_NAME:default_value}

    Example:
        resolver = SecretsResolver()
        token = resolver.resolve("${HA_TOKEN}")
        token_with_default = resolver.resolve("${API_KEY:default_key}")
    """

    PATTERN = re.compile(r"\$\{([^}:]+)(?::([^}]*))?\}")

    def __init__(self, env_file: Path | None = None, load_dotenv: bool = True):
        """
        Initialize the secrets resolver.

        Args:
            env_file: Path to .env file. If None, looks for .env in current directory.
            load_dotenv: Whether to load .env file automatically.
        """
        self._env_file = env_file
        self._load_dotenv = load_dotenv

        if load_dotenv:
            self._load_env_file()

        logger.debug("SecretsResolver initialized")

    def _load_env_file(self) -> None:
        """Load environment variables from .env file if available."""
        try:
            from dotenv import load_dotenv as _load_dotenv

            if self._env_file:
                env_path = self._env_file
            else:
                # Look for .env in current directory and parent directories
                env_path = Path.cwd() / ".env"
                if not env_path.exists():
                    env_path = Path.cwd().parent / ".env"

            if env_path.exists():
                _load_dotenv(dotenv_path=env_path, override=True)
                logger.info(f"Loaded environment from {env_path}")
            else:
                logger.debug("No .env file found, using system environment")
        except ImportError:
            logger.warning("python-dotenv not installed. Install with: pip install python-dotenv")
        except Exception as e:
            logger.warning(f"Failed to load .env file: {e}")

    def resolve(self, value: str) -> str:
        """
        Resolve environment variable references in a string.

        Args:
            value: String that may contain ${VAR_NAME} or ${VAR_NAME:default} patterns.

        Returns:
            String with all environment variable references resolved.

        Raises:
            ValueError: If environment variable is not set and no default is provided.
        """
        if not isinstance(value, str):
            return value  # type: ignore[return-value]

        def replace_var(match: re.Match[str]) -> str:
            var_name = match.group(1)
            default_value = match.group(2)

            env_value = os.environ.get(var_name)

            if env_value is not None:
                return env_value
            elif default_value is not None:
                logger.debug(f"Using default value for {var_name}")
                return default_value
            else:
                raise ValueError(
                    f"Environment variable '{var_name}' is not set and no default value provided"
                )

        result = self.PATTERN.sub(replace_var, value)
        return result

    def resolve_dict(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Recursively resolve environment variables in a dictionary.

        Args:
            data: Dictionary that may contain environment variable references.

        Returns:
            Dictionary with all environment variable references resolved.
        """
        return self._resolve_recursive(data)

    def _resolve_recursive(self, obj: Any) -> Any:
        """Recursively resolve environment variables in nested structures."""
        if isinstance(obj, str):
            return self.resolve(obj)
        elif isinstance(obj, dict):
            return {key: self._resolve_recursive(value) for key, value in obj.items()}
        elif isinstance(obj, list):
            return [self._resolve_recursive(item) for item in obj]
        elif isinstance(obj, tuple):
            return tuple(self._resolve_recursive(item) for item in obj)
        else:
            return obj

    def is_secret_pattern(self, value: str) -> bool:
        """
        Check if a value contains a secret pattern.

        Args:
            value: String to check.

        Returns:
            True if the value contains ${...} pattern.
        """
        if not isinstance(value, str):
            return False
        return bool(self.PATTERN.search(value))

    def validate_no_plain_secrets(
        self, data: dict[str, Any], secret_keys: list[str] | None = None
    ) -> list[str]:
        """
        Validate that sensitive keys don't contain plain-text secrets.

        This method checks if any keys that are likely to contain secrets
        (like 'token', 'password', 'api_key', etc.) contain plain-text values
        instead of environment variable references.

        Args:
            data: Dictionary to validate.
            secret_keys: List of keys that should contain secrets.
                        If None, uses default list of common secret key names.

        Returns:
            List of validation error messages (empty if validation passes).
        """
        if secret_keys is None:
            secret_keys = [
                "token",
                "password",
                "secret",
                "api_key",
                "apikey",
                "auth",
                "credential",
                "key",
                "access_token",
                "refresh_token",
            ]

        errors = []
        self._check_secrets_recursive(data, secret_keys, errors, path="")
        return errors

    def _check_secrets_recursive(
        self, obj: Any, secret_keys: list[str], errors: list[str], path: str
    ) -> None:
        """Recursively check for plain-text secrets."""
        if isinstance(obj, dict):
            for key, value in obj.items():
                current_path = f"{path}.{key}" if path else key

                # Check if this key looks like it should contain a secret
                key_lower = key.lower()
                is_secret_key = any(sk in key_lower for sk in secret_keys)

                # Check for plain-text secrets in sensitive fields
                if (
                    is_secret_key
                    and isinstance(value, str)
                    and not self.is_secret_pattern(value)
                    and value
                    and value not in ("", "changeme", "your_token_here", "xxx")
                ):
                    errors.append(
                        f"Plain-text secret detected at '{current_path}': "
                        f"value should use ${{VAR_NAME}} syntax"
                    )

                self._check_secrets_recursive(value, secret_keys, errors, current_path)

        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                current_path = f"{path}[{i}]"
                self._check_secrets_recursive(item, secret_keys, errors, current_path)


# Global resolver instance (lazy initialization)
_resolver: SecretsResolver | None = None


def get_resolver(env_file: Path | None = None) -> SecretsResolver:
    """
    Get or create the global secrets resolver instance.

    Args:
        env_file: Optional path to .env file.

    Returns:
        SecretsResolver instance.
    """
    global _resolver
    if _resolver is None:
        _resolver = SecretsResolver(env_file=env_file)
    return _resolver


def resolve_secrets(data: dict[str, Any]) -> dict[str, Any]:
    """
    Resolve environment variables in configuration data.

    Convenience function that uses the global resolver.

    Args:
        data: Configuration dictionary with potential ${VAR} references.

    Returns:
        Dictionary with resolved values.
    """
    resolver = get_resolver()
    return resolver.resolve_dict(data)


def validate_secrets(data: dict[str, Any]) -> list[str]:
    """
    Validate that sensitive configuration doesn't contain plain-text secrets.

    Args:
        data: Configuration dictionary to validate.

    Returns:
        List of validation errors (empty if validation passes).
    """
    resolver = get_resolver()
    return resolver.validate_no_plain_secrets(data)
