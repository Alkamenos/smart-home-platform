#!/bin/sh
# Подготовка каталога конфигурации перед стартом платформы.
#
# Зачем это нужно. Каталог конфигурации монтируется томом
# (`./config:/config/behavioral_platform`), и bind-mount НЕ наследует
# содержимое образа: если на хосте каталог пуст, контейнер увидит его пустым.
# При этом `Dockerfile` копирует конфигурацию в `/app/instances`, то есть в
# образе она есть, а в том попадает только при явном переносе.
#
# Без этого шага платформа стартовала с пустым манифестом, а любые правки
# манифеста из интерфейса терялись при пересоздании контейнера: каталог
# `/app/instances/leonids_house` находится в слое контейнера, а не в томе.
# Проверено: после `docker compose down && up -d` хеш манифеста возвращался
# к значению из образа, то есть правка откатывалась молча.
#
# Семантика: копируем только если целевой каталог пуст. Непустой каталог —
# это данные оператора, их нельзя перезаписывать.
#
# Копируется СОДЕРЖИМОЕ $CONFIG_SEED_PATH, а не сам каталог: CONFIG_PATH
# указывает прямо на manifest.yaml, без имени каталога инстанса в пути.

set -eu

CONFIG_PATH="${CONFIG_PATH:-/config/behavioral_platform}"
SEED_PATH="${CONFIG_SEED_PATH:-/app/instances}"

if [ ! -d "$CONFIG_PATH" ]; then
    echo "entrypoint: создаю каталог конфигурации $CONFIG_PATH"
    mkdir -p "$CONFIG_PATH"
fi

if [ -d "$SEED_PATH" ] && [ -n "$(ls -A "$SEED_PATH" 2>/dev/null || true)" ]; then
    if [ -n "$(ls -A "$CONFIG_PATH" 2>/dev/null || true)" ]; then
        echo "entrypoint: каталог $CONFIG_PATH не пуст — данные оператора, посев пропущен"
    else
        echo "entrypoint: переношу конфигурацию из образа ($SEED_PATH → $CONFIG_PATH)"
        cp -a "$SEED_PATH/." "$CONFIG_PATH/"
    fi
else
    echo "entrypoint: посев не требуется — $CONFIG_PATH уже заполнен или $SEED_PATH пуст"
fi

# Права на запись: каталог тома может принадлежать хостовому пользователю.
chmod -R u+rwX "$CONFIG_PATH" 2>/dev/null || true

exec "$@"
