"""Event Store для сохранения истории событий FSM и состояний."""

import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


# Дни недели в порядке отображения карты активности.
WEEKDAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
HOURS_PER_DAY = 24
# Сколько дней недели учитывает карта активности.
ACTIVITY_DAYS = 7


@dataclass
class FsmTransition:
    """Запись о переходе FSM."""

    entity_id: str
    from_state: str
    to_state: str
    trigger_name: str
    trace_id: str | None
    timestamp: float | None = None
    success: bool = True
    reason: str | None = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()


@dataclass
class SensorEvent:
    """Запись о событии сенсора."""

    entity_id: str
    old_state: str
    new_state: str
    event_type: str
    trace_id: str | None
    timestamp: float | None = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()


class EventStore:
    """SQLite хранилище для истории событий и переходов FSM."""

    def __init__(self, db_path: str = "data/history.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Получить соединение с БД."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Инициализировать схему БД."""
        conn = self._get_connection()
        cursor = conn.cursor()

        # История событий сенсоров
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY,
                timestamp REAL,
                entity_id TEXT,
                old_state TEXT,
                new_state TEXT,
                event_type TEXT,
                trace_id TEXT
            )
        """)

        # История переходов FSM
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fsm_transitions (
                id INTEGER PRIMARY KEY,
                timestamp REAL,
                entity_id TEXT,
                from_state TEXT,
                to_state TEXT,
                trigger_name TEXT,
                trace_id TEXT
            )
        """)

        # Manual overrides
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS manual_overrides (
                id INTEGER PRIMARY KEY,
                entity_id TEXT UNIQUE,
                started_at REAL,
                expires_at REAL,
                reason TEXT,
                user_id TEXT
            )
        """)

        # AI suggestions
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_suggestions (
                id INTEGER PRIMARY KEY,
                created_at REAL,
                suggestion_type TEXT,
                title TEXT,
                description TEXT,
                affected_entities TEXT,
                proposed_changes TEXT,
                status TEXT,
                applied_at REAL,
                dismissed_at REAL
            )
        """)

        # Индексы для быстрых запросов
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_entity ON events(entity_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_transitions_entity ON fsm_transitions(entity_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_overrides_entity ON manual_overrides(entity_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_suggestions_status ON ai_suggestions(status)
        """)

        # Признак успеха перехода: раньше в журнал попадали только выполненные
        # переходы, поэтому отказы невозможно было отличить (spec 007, FR-004).
        self._ensure_column(cursor, "fsm_transitions", "success", "INTEGER DEFAULT 1")
        self._ensure_column(cursor, "fsm_transitions", "reason", "TEXT")

        conn.commit()
        conn.close()

    @staticmethod
    def _ensure_column(cursor, table: str, column: str, definition: str) -> None:
        """Добавить колонку в существующую таблицу, если её ещё нет.

        Args:
            cursor: Курсор соединения.
            table: Имя таблицы.
            column: Имя колонки.
            definition: Описание колонки для ALTER TABLE.
        """
        cursor.execute(f"PRAGMA table_info({table})")
        existing = {row["name"] for row in cursor.fetchall()}
        if column not in existing:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def save_fsm_transition(self, transition: FsmTransition):
        """Сохранить переход FSM."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO fsm_transitions
            (timestamp, entity_id, from_state, to_state, trigger_name, trace_id, success, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                transition.timestamp,
                transition.entity_id,
                transition.from_state,
                transition.to_state,
                transition.trigger_name,
                transition.trace_id,
                1 if transition.success else 0,
                transition.reason,
            ),
        )
        conn.commit()
        conn.close()

    def get_recent_transitions(self, entity_id: str, limit: int = 10) -> list[FsmTransition]:
        """Получить последние переходы для устройства."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT entity_id, from_state, to_state, trigger_name, trace_id, timestamp, success, reason
            FROM fsm_transitions
            WHERE entity_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (entity_id, limit),
        )
        rows = cursor.fetchall()
        conn.close()

        return [
            FsmTransition(
                entity_id=row["entity_id"],
                from_state=row["from_state"],
                to_state=row["to_state"],
                trigger_name=row["trigger_name"],
                trace_id=row["trace_id"],
                timestamp=row["timestamp"],
                success=bool(row["success"]) if row["success"] is not None else True,
                reason=row["reason"],
            )
            for row in rows
        ]

    def save_sensor_event(self, event: SensorEvent):
        """Сохранить событие сенсора."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO events
            (timestamp, entity_id, old_state, new_state, event_type, trace_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event.timestamp,
                event.entity_id,
                event.old_state,
                event.new_state,
                event.event_type,
                event.trace_id,
            ),
        )
        conn.commit()
        conn.close()

    def get_events(
        self,
        entity_id: str | None = None,
        from_ts: float | None = None,
        to_ts: float | None = None,
        limit: int = 100,
    ) -> list[SensorEvent]:
        """Получить события с фильтрами."""
        conn = self._get_connection()
        cursor = conn.cursor()

        query = "SELECT * FROM events WHERE 1=1"
        params = []

        if entity_id:
            query += " AND entity_id = ?"
            params.append(entity_id)
        if from_ts:
            query += " AND timestamp >= ?"
            params.append(from_ts)
        if to_ts:
            query += " AND timestamp <= ?"
            params.append(to_ts)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        return [
            SensorEvent(
                entity_id=row["entity_id"],
                old_state=row["old_state"],
                new_state=row["new_state"],
                event_type=row["event_type"],
                trace_id=row["trace_id"],
                timestamp=row["timestamp"],
            )
            for row in rows
        ]

    def save_override(
        self,
        entity_id: str,
        started_at: float,
        expires_at: float,
        reason: str,
        user_id: str = "system",
    ):
        """Сохранить или обновить manual override."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO manual_overrides
            (entity_id, started_at, expires_at, reason, user_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (entity_id, started_at, expires_at, reason, user_id),
        )
        conn.commit()
        conn.close()

    def remove_override(self, entity_id: str):
        """Удалить manual override."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM manual_overrides WHERE entity_id = ?", (entity_id,))
        conn.commit()
        conn.close()

    def get_active_overrides(self) -> list[dict]:
        """Получить активные manual overrides."""
        conn = self._get_connection()
        cursor = conn.cursor()
        current_time = time.time()
        cursor.execute(
            """
            SELECT entity_id, started_at, expires_at, reason, user_id
            FROM manual_overrides
            WHERE expires_at > ?
            ORDER BY expires_at ASC
            """,
            (current_time,),
        )
        rows = cursor.fetchall()
        conn.close()

        return [
            {
                "entity_id": row["entity_id"],
                "started_at": row["started_at"],
                "expires_at": row["expires_at"],
                "reason": row["reason"],
                "user_id": row["user_id"],
            }
            for row in rows
        ]

    def save_ai_suggestion(
        self,
        suggestion_type: str,
        title: str,
        description: str,
        affected_entities: list[str],
        proposed_changes: dict,
    ) -> int:
        """Сохранить AI предложение."""
        import json

        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO ai_suggestions
            (created_at, suggestion_type, title, description, affected_entities, proposed_changes, status)
            VALUES (?, ?, ?, ?, ?, ?, 'pending')
            """,
            (
                time.time(),
                suggestion_type,
                title,
                description,
                json.dumps(affected_entities),
                json.dumps(proposed_changes),
            ),
        )
        suggestion_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return suggestion_id if suggestion_id is not None else 0

    def update_suggestion_status(self, suggestion_id: int, status: str):
        """Обновить статус AI предложения."""
        conn = self._get_connection()
        cursor = conn.cursor()
        now = time.time()

        if status == "applied":
            cursor.execute(
                """
                UPDATE ai_suggestions
                SET status = 'applied', applied_at = ?
                WHERE id = ?
                """,
                (now, suggestion_id),
            )
        elif status == "dismissed":
            cursor.execute(
                """
                UPDATE ai_suggestions
                SET status = 'dismissed', dismissed_at = ?
                WHERE id = ?
                """,
                (now, suggestion_id),
            )
        elif status == "snoozed":
            cursor.execute(
                """
                UPDATE ai_suggestions
                SET status = 'snoozed'
                WHERE id = ?
                """,
                (suggestion_id,),
            )

        conn.commit()
        conn.close()

    def get_suggestions(self, status: str = "pending") -> list[dict]:
        """Получить AI предложения по статусу."""
        import json

        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, created_at, suggestion_type, title, description,
                   affected_entities, proposed_changes, status, applied_at, dismissed_at
            FROM ai_suggestions
            WHERE status = ?
            ORDER BY created_at DESC
            """,
            (status,),
        )
        rows = cursor.fetchall()
        conn.close()

        return [
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "suggestion_type": row["suggestion_type"],
                "title": row["title"],
                "description": row["description"],
                "affected_entities": json.loads(row["affected_entities"]),
                "proposed_changes": json.loads(row["proposed_changes"]),
                "status": row["status"],
                "applied_at": row["applied_at"],
                "dismissed_at": row["dismissed_at"],
            }
            for row in rows
        ]

    def cleanup_old_data(self, days: int = 30):
        """Удалить данные старше N дней."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cutoff_time = time.time() - (days * 24 * 60 * 60)

        cursor.execute("DELETE FROM events WHERE timestamp < ?", (cutoff_time,))
        cursor.execute("DELETE FROM fsm_transitions WHERE timestamp < ?", (cutoff_time,))

        deleted_events = cursor.rowcount
        cursor.execute("SELECT changes()")
        deleted_transitions = cursor.fetchone()[0]

        conn.commit()
        conn.close()

        return {"deleted_events": deleted_events, "deleted_transitions": deleted_transitions}

    def get_activity_heatmap(self, days: int = ACTIVITY_DAYS) -> dict:
        """Собрать активность по дням недели и часам суток.

        Данные берутся из записей переходов и событий: выдуманные значения не
        строятся, поэтому раздел показывает фактическую картину (FR-033, D-2).

        Args:
            days: Сколько дней учитывать при определении «дня недели».

        Returns:
            Словарь с днями, часами, значениями и признаком наличия данных.
        """
        counts = [[0] * HOURS_PER_DAY for _ in WEEKDAY_LABELS]
        total = 0
        cutoff = time.time() - days * HOURS_PER_DAY * 3600

        for timestamp in self._collect_activity_timestamps(cutoff):
            moment = datetime.fromtimestamp(timestamp)
            counts[moment.weekday()][moment.hour] += 1
            total += 1

        return {
            "days": list(WEEKDAY_LABELS),
            "hours": list(range(HOURS_PER_DAY)),
            "data": [
                {"day": label, "values": counts[index]}
                for index, label in enumerate(WEEKDAY_LABELS)
            ]
            if total
            else [],
            "has_data": total > 0,
        }

    def get_hourly_history(self, hours: int = HOURS_PER_DAY) -> dict:
        """Собрать число событий по часам суток за последние сутки.

        Корзины соответствуют настенным часам (``0`` — полночь), поэтому график
        не отображается задом наперёд (FR-033, R-10).

        Args:
            hours: Сколько часов охватывает график.

        Returns:
            Словарь с подписями, значениями и признаком наличия данных.
        """
        counts = [0] * hours
        cutoff = time.time() - hours * 3600
        total = 0

        for timestamp in self._collect_activity_timestamps(cutoff):
            moment = datetime.fromtimestamp(timestamp)
            counts[moment.hour % hours] += 1
            total += 1

        return {
            "labels": [f"{h:02d}:00" for h in range(hours)],
            "data": counts,
            "has_data": total > 0,
        }

    def _collect_activity_timestamps(self, cutoff: float) -> list[float]:
        """Собрать временные метки переходов и событий после отсечки.

        Args:
            cutoff: Отсечка по времени.

        Returns:
            Список меток времени в секундах.
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT timestamp FROM fsm_transitions WHERE timestamp >= ?", (cutoff,))
        timestamps = [row["timestamp"] for row in cursor.fetchall()]
        cursor.execute("SELECT timestamp FROM events WHERE timestamp >= ?", (cutoff,))
        timestamps.extend(row["timestamp"] for row in cursor.fetchall())
        conn.close()
        return [t for t in timestamps if t is not None]
