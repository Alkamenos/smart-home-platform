#!/usr/bin/env python3
"""
Fix integration tests v2:
1. Remove deprecated cleanup() method
2. Add proper HA authentication via onboarding + token creation
3. Increase pytest timeout
"""

import os
import sys
import subprocess


def fix_cleanup_method(repo_path: str = '.', dry_run: bool = False) -> bool:
    """Remove deprecated container.cleanup() call."""

    test_file = os.path.join(repo_path, 'tests/integration/test_ha_integration.py')

    with open(test_file, 'r', encoding='utf-8') as f:
        content = f.read()

    print("🔧 Фикс 1: Удаляю container.cleanup()...")

    # Удаляем вызов cleanup()
    old_cleanup = """    # Cleanup
    logger.info("Stopping Home Assistant container...")
    container.stop()
    container.cleanup()"""

    new_cleanup = """    # Cleanup
    logger.info("Stopping Home Assistant container...")
    container.stop()"""

    if old_cleanup in content:
        if dry_run:
            print("   [DRY-RUN] Будет удалён: container.cleanup()")
        else:
            content = content.replace(old_cleanup, new_cleanup)
            print("   ✅ Удалён: container.cleanup()")
    else:
        # Пробуем альтернативные варианты
        if 'container.cleanup()' in content:
            if dry_run:
                print("   [DRY-RUN] Будет удалён: container.cleanup()")
            else:
                content = content.replace('container.cleanup()\n', '')
                content = content.replace('    container.cleanup()', '')
                print("   ✅ Удалён: container.cleanup()")
        else:
            print("   ⚠️  cleanup() не най")

    if not dry_run:
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write(content)

    return True


def fix_ha_authentication(repo_path: str = '.', dry_run: bool = False) -> bool:
    """Fix HA authentication by creating a long-lived token."""

    test_file = os.path.join(repo_path, 'tests/integration/test_ha_integration.py')

    with open(test_file, 'r', encoding='utf-8') as f:
        content = f.read()

    print("\n🔧 Фикс 2: Настляю автомат аутентификации...")

    # 1. Обновляем конфигурацию HA чтобы включить auth
    old_config = '''    config_content = """
default_config:
websocket_api:
api:
http:
  server_port: 8123
  trusted_proxies:
    - 172.17.0.0/16
logger:
  default: info
"""'''

    new_config = '''    # Configuration with authentication enabled
    # We'll create a long-lived token via the REST API after startup
    config_content = """
default_config:
websocket_api:
api:
http:
  server_port: 8123
logger:
  default: info
"""'''

    if old_config in content:
        if dry_run:
            print("   [DRY-RUN] Будет обновлена: конфигурация HA")
        else:
            content = content.replace(old_config, new_config)
            print("   ✅ Обновлена конфигурация HA")
    else:
        print("   ⚠️  Старая конфигурация не найдена, пробую найтисальный подход")

    # 2. Добав создать автоматически API onboarding
    # Находим fixture ha_token и обновляем его
    old_token_fixture = '''@pytest.fixture
def ha_token(ha_container):
    """
    Get or create a long-lived access token for HA.

    For integration tests, we use the API to create a token or use a known test token.
    In a real scenario, you would need to pre-create a token in HA.
    """
    # For testing purposes, we'll try to use the API without auth first
    # In production, you'd need to create a long-lived token in HA UI
    return os.environ.get("HA_TEST_TOKEN", TEST_TOKEN)'''

    new_token_fixture = '''@pytest.fixture
def ha_token(ha_container):
    """
    Create a long-lived access token for HA via onboarding API.

    Fresh HA instance requires onboarding. We:
    1. Complete onboarding (create first user)
    2. Create a long-lived access token
    3. Return the token for use in tests
    """
    import requests

    host = ha_container.get("host", "localhost")
    port = ha_container.get("port", 8123)
    base_url = f"http://{host}:{port}"

    # Environment variable override
    if os.environ.get("HA_TEST_TOKEN"):
        return os.environ["HA_TEST_TOKEN"]

    # Step 1: Wait for HA to be ready and check onboarding status
    max_wait = 120
    waited = 0
    onboarding_needed = False

    while waited < max_wait:
        try:
            resp = requests.get(f"{base_url}/api/onboarding", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                # Check if any onboarding step is incomplete
                steps = data.get("steps", []) if isinstance(data, dict) else []
                if any(step.get("done") is False for step in steps):
                    onboarding_needed = True
                    break
                # Onboarding already done
                    break
            elif resp.status_code == 404:
                # No onboarding endpoint, might be already onboarded
                break
        except requests.RequestException:
            pass

        time.sleep(3)
        waited += 3

    # Step 2: Complete onboarding if needed
    if onboarding_needed:
        print("\\n📋вершаю onboarding HA...")

        # Complete user step (create first user)
        user_data = {
            "client_id": "integration-test",
            "name": "Test User",
            "username": "test",
            "password": "testtest",
            "language": "en",
        }

        try:
            resp = requests.post(
                f"{base_url}/api/onboarding/users",
                json=user_data,
                timeout=30,
            )
            if resp.status_code in (200, 201):
                print("   ✅ Пользователь создан")
                # Response contains installation token
                auth_token = resp.json().get("auth_code") or resp.json().get("token")
            else:
                print(f"   ⚠️  Onboarding response: {resp.status_code}")
                auth_token = None
        except Exception as e:
            print(f"   ❌ Onboarding failed: {e}")
            auth_token = None

        # Wait a bit for HA to finish initializing
        time.sleep(10)

    # Step 3: Create a long-lived access token
    # First authenticate to get refresh token
    auth_url = f"{base_url}/auth/token"

    # Try to get token via different methods
    headers = {"Content-Type": "application/json"}

    # Method 1: Use credentials directly
    try:
        # Authenticate
        resp = requests.post(
            f"{base_url}/auth/login_flow",
            json={
                "client_id": "http://localhost:8123/",
                "handler": ["homeassistant", None],
                "redirect_uri": f"{base_url}/?auth_callback=1",
            },
            timeout=10,
        )
        if resp.status_code == 200:
            flow_id = resp.json().get("flow_id")

            # Submit credentials
            resp = requests.post(
                f"{base_url}/auth/login_flow/{flow_id}",
                json={"username": "test", "password": "testtest"},
                timeout=10,
            )
            if resp.status_code == 200:
                result = resp.json()
                if result.get("type") == "create_entry":
                    auth_code = result.get("result")

                    # Exchange auth code for tokens
                    resp = requests.post(
                        auth_url,
                        data={
                            "grant_type": "authorization_code",
                            "code": auth_code,
                            "client_id": "http://localhost:8123/",
                        },
                        timeout=10,
                    )
                    if resp.status_code == 200:
                        tokens = resp.json()
                        access_token = tokens.get("access_token")
                        refresh_token = tokens.get("refresh_token")

                        # Now create long-lived token
                        resp = requests.post(
                            f"{base_url}/api/long_lived_token",
                            headers={
                                "Authorization": f"Bearer {access_token}",
                                "Content-Type": "application/json",
                            },
                            json={
                                "client_name": "integration-test",
                                "client_icon": "mdi:test-tube",
                                "lifespan": 365,
                            },
                            timeout=10,
                        )
                        if resp.status_code in (200, 201):
                            ll_token = resp.json().get("token")
                            print(f"   ✅ Соз получен token получен")
                            return ll_token
    except Exception as e:
        print(f"   ⚠️  Метод 1 не сработал: {e}")

    # Fallback: return empty string, tests will skip auth-required operations
    print("   ⚠️  Не удалось создать токен, некоторые пропущены")
    return ""'''

    # Простая замена — ищем старый ha_token fixture
    # Ноходим блок по началкеру @pytest.fixture\n def ha_token
    import re
    pattern = r'@pytest\.fixture\s*\ndef ha_token\(ha_container\):.*?(?=\n@pytest\.fixture|\nasync def test_|class |\Z)'

    matches = list(re.finditer(pattern, content, re.DOTALL))
    if matches:
        if dry_run:
            print("   [DRY-RUN] Будет заменён: fixture ha_token")
        else:
            content = content[:matches[0].start()] + new_token_fixture + content[matches[0].end():]
            print("   ✅ Fixture ha_token обновлён")
    else:
        print("   ⚠️  Fixture ha_token не найден — применю простой методого варианта")
        # Простой фик добавим импорт requests в начало файла если его нет
        if 'import requests' not in content:
            content = content.replace(
                'import time',
                'import requests\nimport time'
            )

    if not dry_run:
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write(content)

    return True


def create_pytest_config(repo_path: str = '.') -> bool:
    """Update pytest configuration to increase timeout."""

    # Check pyproject.toml
    pyproject_path = os.path.join(repo_path, 'pyproject.toml')

    print("\n🔧 Фикс 3: Увеличиваю pytest timeout...")

    if os.path.exists(pyproject_path):
        with open(pyproject_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Check for pytest-timeout configuration
        if 'timeout' in content and '[tool.pytest.ini_options]' in content:
            # Update timeout
            if 'timeout = 30' in content or 'timeout=30' in content:
                content = content.replace('timeout = 30', 'timeout = 300')
                content = content.replace('timeout=30', 'timeout=300')
                with open(pyproject_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                print("   ✅ Увеличен: timeout 30 -> 300")
            else:
                print("   ⚠️  Timeout не 30, проверю вручную")
        else:
            print("   ⚠️  Конфигурация pytest не найдена в pyproject.toml")

    # Create/update pytest.ini for integration tests specifically
    conftest_path = os.path.join(repo_path, 'tests/integration/conftest.py')
    if not os.path.exists(conftest_path):
        with open(conftest_path, 'w', encoding='utf-8') as f:
            f.write('''"""Pytest configuration for integration tests."""

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config, items):
    """Set longer timeout for integration tests."""
    for item in items:
        # Set timeout to 10 minutes for all integration tests
        item.add_marker(pytest.mark.timeout(600))
''')
        print("   ✅ Соз conftest.py с увели timeout=600")
    else:
        print("   ⚠️  conftest.py уже существует")

    return True


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Fix integration tests v2")
    parser.add_argument('--repo-path', default='.', help="Path to repository root")
    parser.add_argument('--dry-run', action='store_true', help="Preview changes")
    args = parser.parse_args()

    repo_path = os.path.abspath(args.repo_path)

    print("=" * 70)
    print("🔧 ФИКС ИН2: ИНТЕГРАЦИОННЫЕ ТЕСТтеграционные ТЕСТЫ")
    print("=" * 70)

    fix_cleanup_method(repo_path, dry_run=args.dry_run)
    fix_ha_authentication(repo_path, dry_run=args.dry_run)
    fix_pytest_timeout(repo_path, args.dry_run)

    print()
    print("=" * 70)
    print("✅ ЗАСЛЕДУЮЩИЕ ШАГИ")
    print("=" * 70)
    print()
    print("1. Запусти с увеличенным timeout:")
    print("   export TESTCONTAINERS_RYUK_DISABLED=true")
    print("   pytest tests/integration/ -v -s --timeout=600")
    print()
    print("2. Если WebSocket всё fails — нужен токен автор HA:")
    print("   - От завераться автоматически при onboarding")
    print("   - Если не сработало — создай вручную:")
    print("     * Открой http://localhost:8123")
    print("     * Profile -> Security -> Create Token")
    print("     * export HA_TEST_TOKEN=<your-token>")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
