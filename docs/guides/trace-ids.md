# 🔍 Understanding Trace IDs

Every event and action in the platform has a unique `trace_id` (first 8 characters of UUID) for debugging:

```
[trace_id: a1b2c3d4] HAAdapter: state_change received for binary_sensor.kitchen_motion: 'off' -> 'on'
[trace_id: a1b2c3d4] EventBus: Publishing event: state_change
[trace_id: a1b2c3d4] FSM Engine: Entity binary_sensor.kitchen_motion: Transition 'idle' -> 'active' triggered by 'motion_detected'
[trace_id: a1b2c3d4] HAAdapter: calling service light.turn_on for light.kitchen
[trace_id: a1b2c3d4] HAAdapter: service light.turn_on called successfully
```

**Search by trace_id in logs** to follow the complete chain of events across all components.
