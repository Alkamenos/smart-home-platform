"""
ПРАКТИЧЕСКОЕ РУКОВОДСТВО ПО UNIT ТЕСТАМ МОДЕЛЕЙ
=================================================

Файл: tests/unit/test_models.py
Язык: Python 3.10+
Фреймворк: pytest
Версия тестов: 1.0.0


БЫСТРЫЙ СТАРТ
==============

1. Установка зависимостей (если ещё не установлены):
   pip install -e ".[dev]"

2. Запуск всех тестов моделей:
   pytest tests/unit/test_models.py -v

3. Запуск с отчётом о покрытии:
   pytest tests/unit/test_models.py -v --cov=src.core.models

4. Запуск быстрых тестов (без медленных):
   pytest tests/unit/test_models.py -v -m "not slow"


ПРИМЕРЫ КОМАНД
===============

# Запуск конкретного класса тестов
pytest tests/unit/test_models.py::TestHASourceCreation -v

# Запуск конкретного теста
pytest tests/unit/test_models.py::TestHASourceCreation::test_создание_с_валидными_данными -v

# Запуск всех тестов HASource
pytest tests/unit/test_models.py -k "HASource" -v

# Запуск всех тестов Device
pytest tests/unit/test_models.py -k "Device" -v

# Запуск тестов валидации
pytest tests/unit/test_models.py -k "Validation" -v

# Запуск с детальным выводом (показывает переменные)
pytest tests/unit/test_models.py -vv

# Запуск с остановкой на первой ошибке
pytest tests/unit/test_models.py -v -x

# Запуск с остановкой при первом сбое (не пропускает даже предупреждения)
pytest tests/unit/test_models.py -v --tb=short

# Запуск с профилированием времени
pytest tests/unit/test_models.py -v --durations=10

# Запуск параллельно (требует pytest-xdist)
pytest tests/unit/test_models.py -v -n auto


СТРУКТУРА ТЕСТОВ
==================

тесты организованы в следующем порядке:

1. Тесты HASource (26 тестов)
   - TestHASourceCreation
   - TestHASourceNameValidation
   - TestHASourceURLValidation
   - TestHASourceTokenValidation
   - TestHASourceStatusValidation
   - TestHASourceOptionalFields

2. Тесты Device (30 тестов)
   - TestDeviceCreation
   - TestDeviceEntityIDValidation
   - TestDeviceDeviceTypeValidation
   - TestDeviceStateValidation
   - TestDeviceStatusValidation
   - TestDeviceNameValidation

3. Тесты DeviceConfig (25 тестов)
   - TestDeviceConfigCreation
   - TestDeviceConfigDisplayNameValidation
   - TestDeviceConfigTagsValidation
   - TestDeviceConfigLocationValidation
   - TestDeviceConfigDescriptionValidation

4. Тесты DeviceCommand (27 тестов)
   - TestDeviceCommandCreation
   - TestDeviceCommandNameValidation
   - TestDeviceCommandHAServiceValidation
   - TestDeviceCommandTimeoutValidation
   - TestDeviceCommandParametersValidation
   - TestDeviceCommandSafetyValidation

5. Тесты DeviceAccess (17 тестов)
   - TestDeviceAccessCreation
   - TestDeviceAccessRoleValidation
   - TestDeviceAccessPermissions

6. Дополнительные тесты (10 тестов)
   - TestModelsJSONDeserialization
   - TestCommandExecutionModels
   - TestModelsUUIDHandling
   - TestModelsTimestamps
   - TestEdgeCases


ПРОВЕРКА КОДА
==============

# Проверка типов (mypy)
mypy tests/unit/test_models.py

# Линтинг (ruff)
ruff check tests/unit/test_models.py

# Форматирование (ruff format)
ruff format tests/unit/test_models.py

# Все проверки вместе
ruff check tests/unit/test_models.py && mypy tests/unit/test_models.py


ИНТЕГРАЦИЯ С CI/CD
===================

Для GitHub Actions добавьте в .github/workflows/tests.yml:

  - name: Запуск unit тестов моделей
    run: pytest tests/unit/test_models.py -v --cov=src.core.models

Для GitLab CI добавьте в .gitlab-ci.yml:

  test:models:
    script:
      - pytest tests/unit/test_models.py -v --cov=src.core.models


ОТЛАДКА ТЕСТОВ
================

# Запуск с выводом print() и logging
pytest tests/unit/test_models.py -v -s

# Запуск с pdb (debugger) при ошибке
pytest tests/unit/test_models.py -v --pdb

# Запуск с pdb и остановкой перед началом
pytest tests/unit/test_models.py -v --pdb -x

# Запуск конкретного теста для отладки
pytest tests/unit/test_models.py::TestHASourceCreation::test_创建_с_валидными_данными -v -s


РАСШИРЕНИЕ ТЕСТОВ
==================

Если нужно добавить новые тесты:

1. Добавьте новый класс тестов в конец файла:

   class TestNewFeature:
       \"\"\"Тесты новой функции.\"\"\"

       def test_пример(self):
           \"\"\"Описание теста.\"\"\"
           assert True

2. Используйте существующие fixtures:

   def test_с_фиксчей(self, valid_ha_source_data):
       \"\"\"Тест с использованием fixture.\"\"\"
       source = HASource(**valid_ha_source_data)
       assert source.name == "Home Assistant Pro"

3. Создавайте новые fixtures для новых типов данных:

   @pytest.fixture
   def valid_new_model_data():
       return {"field": "value"}

4. Следуйте соглашению AAA (Arrange-Act-Assert)


ЧАСТЫЕ ВОПРОСЫ
==============

Q: Как запустить только тесты валидации?
A: pytest tests/unit/test_models.py -k "Validation" -v

Q: Как запустить только тесты конкретной модели?
A: pytest tests/unit/test_models.py -k "HASource" -v

Q: Как увидеть покрытие кода?
A: pytest tests/unit/test_models.py --cov=src.core.models --cov-report=html

Q: Почему тест падает с ValidationError?
A: Это ожидаемо - тесты проверяют что невалидные данные вызывают ошибки.
   Используйте pytest.raises(ValidationError) для проверки таких случаев.

Q: Как создать собственный test fixture?
A: Используйте декоратор @pytest.fixture перед функцией в классе или в conftest.py

Q: Как пропустить тест?
A: Используйте @pytest.mark.skip(reason="...") над методом теста

Q: Как пометить тест как ожидаемо падающий?
A: Используйте @pytest.mark.xfail(reason="...") над методом теста


ОЖИДАЕМОЕ ВРЕМЯ ВЫПОЛНЕНИЯ
=============================

Общее время: 2-5 секунд
- HASource тесты: ~0.5 сек
- Device тесты: ~0.5 сек
- DeviceConfig тесты: ~0.4 сек
- DeviceCommand тесты: ~0.4 сек
- DeviceAccess тесты: ~0.3 сек
- Дополнительные тесты: ~0.3 сек
- Служебные операции: ~1.5 сек


ПОДДЕРЖИВАЕМЫЕ ПЛАТФОРМЫ
=========================

✓ Linux (Ubuntu, Debian)
✓ macOS (Intel и Apple Silicon)
✓ Windows (с WSL рекомендуется)
✓ Docker контейнеры

Требуемые версии:
✓ Python 3.10+
✓ pytest 8.0+
✓ pydantic 2.0+


ЛИЦЕНЗИЯ И ПРАВОВАЯ ИНФОРМАЦИЯ
================================

Copyright 2026 Leonid Artemev
SPDX-License-Identifier: Apache-2.0

Все тесты и документация распространяются под лицензией Apache 2.0
"""
