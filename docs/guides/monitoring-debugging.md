# 📊 Monitoring and Debugging

## Log Configuration

Add to your `logging.yaml` in HA:

```yaml
logger:
  default: warning
  logs:
    pyscript.smart_home_bridge: info
    src.smart_home: debug
```

## Finding Issues by Trace ID

```bash
# Search logs for specific trace
grep "a1b2c3d4" /config/home-assistant.log

# Follow all events for an entity
grep "kitchen_motion" /config/home-assistant.log | grep "trace_id"
```
