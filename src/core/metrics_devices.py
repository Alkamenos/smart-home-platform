"""Device integration metrics for the platform (spec 018, T059).

Extracted from MetricsCollector: observations about device sync, commands,
errors, availability and cache.
"""

# mypy: disable-error-code="attr-defined"

from __future__ import annotations


class MetricsDevicesMixin:
    """Record device integration and cache observations."""

    def record_device_sync_duration(
        self,
        source_id: str,
        device_type: str,
        duration_seconds: float,
    ) -> None:
        """Записывает время синхронизации для отдельного устройства.

        Args:
            source_id: Идентификатор источника (например, UUID как строка)
            device_type: Тип устройства (например, "light", "switch", "sensor")
            duration_seconds: Время синхронизации в секундах
        """
        if self._initialized and self._device_sync_duration_seconds:
            self._device_sync_duration_seconds.labels(
                source_id=source_id,
                device_type=device_type,
            ).observe(duration_seconds)

    def record_source_sync_duration(
        self,
        source_id: str,
        total_duration_seconds: float,
    ) -> None:
        """Записывает общее время синхронизации для всех устройств источника.

        Args:
            source_id: Идентификатор источника
            total_duration_seconds: Общее время синхронизации в секундах
        """
        if self._initialized and self._source_sync_total_seconds:
            self._source_sync_total_seconds.labels(
                source_id=source_id,
            ).observe(total_duration_seconds)

    def record_command_sent(
        self,
        source_id: str,
        device_type: str,
        command_type: str,
    ) -> None:
        """Записывает отправку команды на устройство.

        Args:
            source_id: Идентификатор источника
            device_type: Тип устройства
            command_type: Тип команды (например, "turn_on", "turn_off")
        """
        if self._initialized and self._device_commands_total:
            self._device_commands_total.labels(
                source_id=source_id,
                device_type=device_type,
                command_type=command_type,
            ).inc()

    def record_command_success(
        self,
        source_id: str,
        device_type: str,
        command_type: str,
    ) -> None:
        """Записывает успешное выполнение команды.

        Args:
            source_id: Идентификатор источника
            device_type: Тип устройства
            command_type: Тип команды
        """
        if self._initialized and self._device_commands_success:
            self._device_commands_success.labels(
                source_id=source_id,
                device_type=device_type,
                command_type=command_type,
            ).inc()

    def record_command_failed(
        self,
        source_id: str,
        device_type: str,
        command_type: str,
        error_type: str,
    ) -> None:
        """Записывает ошибку при выполнении команды.

        Args:
            source_id: Идентификатор источника
            device_type: Тип устройства
            command_type: Тип команды
            error_type: Тип ошибки (например, "timeout", "connection_error")
        """
        if self._initialized and self._device_commands_failed:
            self._device_commands_failed.labels(
                source_id=source_id,
                device_type=device_type,
                command_type=command_type,
                error_type=error_type,
            ).inc()

    def record_manual_lockout_block(
        self,
        device_id: str,
        remaining_sec: float | None = None,
    ) -> None:
        """Записать отказ автоматической команды по ручной блокировке.

        Остаток срока в счётчик не входит — он меняется по ходу дела, и счётчик
        с такой меткой раздувался бы на каждом опросе. Он пишется в журнал.

        Args:
            device_id: Идентификатор устройства, которым управлял человек.
            remaining_sec: Сколько секунд осталось до конца блокировки; для
                диагностики в журнале.
        """
        if self._initialized and self._manual_lockout_blocks_total:
            self._manual_lockout_blocks_total.labels(device_id=device_id).inc()

    def manual_lockout_blocks_total_value(self) -> int:
        """Суммарное число отказов по ручной блокировке.

        Существует ради проверок: счётчик с метками читать неудобно, а нужно
        проверить сам факт учёта — иначе приёмка «свет не включился» нечем
        подтвердить.

        Returns:
            Сумма по всем устройствам; 0, если счётчик не инициализирован.
        """
        counter = self._manual_lockout_blocks_total
        if not self._initialized or counter is None:
            return 0
        total = 0.0
        for metric in counter.collect():
            for sample in metric.samples:
                # Служебный образец `_created` несёт время создания счётчика, а не число
                # число отказов: без фильтра сумма была бы временем запуска.
                if sample.name.endswith("_created"):
                    continue
                total += sample.value
        return int(total)

    def record_connection_error(
        self,
        source_id: str,
        error_type: str,
    ) -> None:
        """Записывает ошибку соединения с источником.

        Args:
            source_id: Идентификатор источника
            error_type: Тип ошибки (например, "timeout", "refused", "dns_failed")
        """
        if self._initialized and self._device_connection_errors_total:
            self._device_connection_errors_total.labels(
                source_id=source_id,
                error_type=error_type,
            ).inc()

    def record_sync_error(
        self,
        source_id: str,
        error_type: str,
    ) -> None:
        """Записывает ошибку синхронизации.

        Args:
            source_id: Идентификатор источника
            error_type: Тип ошибки (например, "invalid_response", "parse_error")
        """
        if self._initialized and self._device_sync_errors_total:
            self._device_sync_errors_total.labels(
                source_id=source_id,
                error_type=error_type,
            ).inc()

    def set_devices_available(
        self,
        source_id: str,
        device_type: str,
        count: int,
    ) -> None:
        """Устанавливает количество доступных устройств.

        Args:
            source_id: Идентификатор источника
            device_type: Тип устройства
            count: Количество доступных устройств
        """
        if self._initialized and self._devices_available:
            self._devices_available.labels(
                source_id=source_id,
                device_type=device_type,
            ).set(count)

    def set_devices_unavailable(
        self,
        source_id: str,
        device_type: str,
        count: int,
    ) -> None:
        """Устанавливает количество недоступных устройств.

        Args:
            source_id: Идентификатор источника
            device_type: Тип устройства
            count: Количество недоступных устройств
        """
        if self._initialized and self._devices_unavailable:
            self._devices_unavailable.labels(
                source_id=source_id,
                device_type=device_type,
            ).set(count)

    def set_sources_connected_count(self, count: int) -> None:
        """Устанавливает количество подключенных источников.

        Args:
            count: Количество подключенных источников
        """
        if self._initialized and self._sources_connected:
            self._sources_connected.set(count)

    def set_cache_size(self, size_bytes: int) -> None:
        """Устанавливает размер кэша.

        Args:
            size_bytes: Размер кэша в байтах
        """
        if self._initialized and self._cache_size:
            self._cache_size.set(size_bytes)

    def record_cache_hit(self, cache_type: str) -> None:
        """Записывает попадание в кэш.

        Args:
            cache_type: Тип кэша (например, "device", "config")
        """
        if self._initialized and self._cache_hits:
            self._cache_hits.labels(cache_type=cache_type).inc()

    def record_cache_miss(self, cache_type: str) -> None:
        """Записывает промах кэша.

        Args:
            cache_type: Тип кэша (например, "device", "config")
        """
        if self._initialized and self._cache_misses:
            self._cache_misses.labels(cache_type=cache_type).inc()
