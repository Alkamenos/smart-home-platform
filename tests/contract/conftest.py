"""Доступ к общей инфраструктуре тестов для каталога `tests/contract/`.

Фикстуры идентичности и изоляции персистентности описаны в
`tests/integration/conftest.py` (спека 009, T004). Контрактные тесты разграничения
прав должны проверять то же самое, что и интеграционные, — через HTTP, — иначе
проверялось бы не то.

Фикстуры pytest не наследуются между каталогами, поэтому они импортируются
явно. Список задан импортом, а не «звёздочкой», чтобы новые фикстуры не попадали
сюда случайно: добавление должно быть осознанным.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from tests.integration.conftest import (
    MANIFEST_RELPATH,
    NO_RIGHTS_USER_ID,
    OTHER_USER_ID,
    REGULAR_USER_ID,
    VIEWER_USER_ID,
    admin_headers,
    admin_user_id,
    grant_viewer,
    ha_client,
    ha_refused,
    ha_states,
    ha_timeout,
    ha_unavailable,
    isolated_app,
    isolated_client,
    isolated_workdir,
    no_rights_headers,
    other_headers,
    project_root,
    regular_user_id,
    repo_data_guard,
    synced_device_id,
    viewer_headers,
)


__all__ = [
    "MANIFEST_RELPATH",
    "NO_RIGHTS_USER_ID",
    "OTHER_USER_ID",
    "REGULAR_USER_ID",
    "VIEWER_USER_ID",
    "admin_headers",
    "admin_user_id",
    "grant_viewer",
    "ha_client",
    "ha_refused",
    "ha_states",
    "ha_timeout",
    "ha_unavailable",
    "isolated_app",
    "isolated_client",
    "isolated_workdir",
    "no_rights_headers",
    "other_headers",
    "project_root",
    "regular_user_id",
    "repo_data_guard",
    "synced_device_id",
    "viewer_headers",
]
