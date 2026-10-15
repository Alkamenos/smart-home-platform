/**
 * Типы ответов платформы, которые использует интерфейс (спека 017).
 *
 * Формы повторяют реальные ответы API (см. contracts/http-api.md и
 * `core/models/location.py`): снимок локации отдаёт показания по ролям, а не
 * плоским списком.
 */

export interface Session {
    user_id: string;
    is_admin: boolean;
    display_name: string;
}

export interface Reading {
    value: unknown;
    unit: string | null;
    at: string;
    stale: boolean;
    available: boolean;
    entity_id: string;
    /** Какую батарейку покупать, когда эта сядет (из манифеста). */
    battery_type?: string | null;
}

export interface SeriesPoint {
    at: string;
    value: number;
}

export interface LocationRef {
    id: string;
    name: string;
    kind: string;
}

export interface LocationSnapshot {
    location: LocationRef;
    at: string;
    available: boolean;
    readings: Record<string, Reading[]>;
    derived: Record<string, unknown>;
    series?: Record<string, SeriesPoint[]>;
}

export interface FSMState {
    fsm_id: string;
    device_id: string;
    behavior: string;
    state: string;
    since: string | null;
}

export interface Device {
    id: string;
    name: string;
    ha_entity_id: string;
    device_type: string;
    status: string;
    state: { state?: unknown } | Record<string, unknown>;
    location: string | null;
    room_id: string | null;
    room_name: string | null;
    fsm: FSMState[];
}

export interface Alert {
    kind: string;
    subject: string;
    severity: string;
    detail: string;
    at: string | null;
}

export interface Overview {
    generated_at: string;
    house_name: string;
    locations: LocationSnapshot[];
    devices: Device[];
    alerts: Alert[];
}

export interface Behavior {
    template: string;
    priority: number;
    params?: Record<string, unknown>;
}

export interface AutomationInfo {
    configured: boolean;
    fsm_ids: string[];
    reason: string | null;
}

export interface DeviceDetail {
    id: string;
    name: string;
    display_name: string | null;
    device_type: string;
    status: string;
    state: Record<string, unknown>;
    ha_entity_id: string;
    ha_area_id: string | null;
    fsm: FSMState[];
    behaviors: Behavior[];
    automation: AutomationInfo;
    decision: Decision | null;
}

export interface CommandResponse {
    id: string;
    device_id: string;
    command_name: string;
    status: string;
    automation_synced: boolean;
    result: unknown;
}

export interface LocationSummary {
    id: string;
    name: string;
    kind: string;
    sensor_count: number;
    sensors: Record<string, string | string[]>;
}

export interface Decision {
    at: string;
    outcome: string;
    reason_code: string | null;
    reason_text: string;
    trigger: string | null;
}

export interface Override {
    entity_id: string;
    started_at: number;
    expires_at: number;
    reason: string;
    user_id: string;
}

export interface JournalRecord {
    at: string;
    at_ts: number;
    kind: string;
    entity_id: string;
    title: string;
    message: string;
    trace_id: string | null;
    old_value: unknown;
    value: unknown;
}

export interface JournalResponse {
    count: number;
    records: JournalRecord[];
    next_cursor: number | null;
}

export interface Source {
    id: string;
    name: string;
    url: string;
    status: string;
    last_sync: string | null;
    last_error: string | null;
    created_at: string;
    updated_at: string;
}

export interface AvailableDevice {
    entity_id: string;
    friendly_name: string;
    device_type: string;
    area_id: string | null;
    area_name: string | null;
    state: string;
    icon: string | null;
}

export interface DiscoveryData {
    source_id: string;
    areas: Array<{ id: string; name: string }>;
    available_devices: AvailableDevice[];
    available_device_count: number;
    error: string | null;
}

export interface RoomOption {
    id: string;
    name: string;
}

export interface ManifestResponse {
    manifest: Record<string, unknown>;
    has_unsaved_changes: boolean;
}

export interface FieldError {
    loc: string;
    message: string;
}

export interface DeviceAccess {
    id: string;
    user_id: string;
    role: string;
}

export interface ReadinessCheck {
    ok: boolean;
    detail?: string;
    [key: string]: unknown;
}

export interface Readiness {
    ready: boolean;
    failed: string[];
    checks: Record<string, ReadinessCheck>;
}

export interface PlatformLog {
    timestamp: string;
    level: string;
    message: string;
}
