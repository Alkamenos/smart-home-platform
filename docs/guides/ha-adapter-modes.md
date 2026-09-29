# 🔄 HA Adapter Modes

## Pyscript Mode (Recommended)

**Pros:**
- Hot-reload in 1 second
- Direct access to `hass` object
- No WebSocket complexity
- Runs inside HA process

**Usage:**
```python
adapter = HAAdapter(mode="pyscript", engine=engine, hass=hass)
```

## WebSocket Mode (Standalone)

**Pros:**
- Runs outside HA process
- Can be deployed separately
- Better isolation

**Cons:**
- Requires `homeassistant-websocket` library
- More complex reconnection logic

**Usage:**
```python
adapter = HAAdapter(
    mode="websocket",
    engine=engine,
    ws_url="ws://localhost:8123/api/websocket",
    token="your_long_lived_token",
)
await adapter.start()
```
