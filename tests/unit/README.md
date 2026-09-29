# Инструкция по запуску unit тестов для DeviceService

Для запуска всех тестов:
    pytest tests/unit/test_device_service.py -v

Для запуска конкретного класса тестов:
    pytest tests/unit/test_device_service.py::TestDeviceServiceInitialization -v

Для запуска конкретного теста:
    pytest tests/unit/test_device_service.py::TestParseDevices::test_parse_single_device -v

Для запуска с покрытием:
    pytest tests/unit/test_device_service.py --cov=src.services.device_service --cov-report=html

Для запуска с выводом логов:
    pytest tests/unit/test_device_service.py -v -s

Требования:
- pytest
- pytest-asyncio
- pydantic
- loguru

Установка зависимостей:
    pip install pytest pytest-asyncio pydantic loguru
