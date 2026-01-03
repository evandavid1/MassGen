# Current Issue: WebSocket Disconnects During Coordination

**Date:** 2026-01-03
**Status:** Investigating

## Symptoms

1. **"WebSocket connection failed" banner** appears during coordination
2. **Agent cards stuck on "Waiting"** with "Answers: 0"
3. **"Coordination in progress..."** shown at bottom but no updates
4. Header shows **"Connected"** but error banner persists

## Console Logs

```
WebSocket disconnected: 1006
WebSocket connected
[DEBUG] WebSocket event: state_snapshot Object
```

- **Code 1006** = Abnormal Closure (connection dropped without proper close frame)
- WebSocket reconnects but misses events during disconnect
- Only `state_snapshot` received after reconnect (no `agent_status`, `new_answer`, etc.)

## What's Happening

1. Coordination starts successfully
2. WebSocket connection drops mid-coordination (code 1006)
3. WebSocket auto-reconnects
4. Server sends `state_snapshot` to restore state
5. But events during disconnect are lost - cards don't update
6. Backend continues processing, but UI is stale

## Possible Causes

### 1. Railway Proxy Timeout
Railway's reverse proxy may disconnect idle WebSocket connections. During coordination, if there's a gap between events, the connection may timeout.

### 2. Server Resource Constraints
Railway container may be resource-constrained, causing the event loop to stall and drop the WebSocket connection.

### 3. Large Message Buffering
If agents generate large responses, the WebSocket buffer may fill up, causing disconnection.

### 4. asyncio Task Scheduling
The `asyncio.create_task()` for broadcasts may not be getting scheduled in time, causing backpressure.

## Debug Logging Added

```python
# web_display.py - update_agent_content
print(f"[WebDisplay] update_agent_content: agent={agent_id}, type={content_type}, len={len(content)}", flush=True)

# server.py - broadcast
print(f"[Server] broadcast {msg_type} to {num_clients} client(s)", flush=True)
```

## Next Steps

1. **Check Railway logs** for debug output during the disconnect
2. **Look for patterns** - does it always disconnect at the same point?
3. **Check memory/CPU** on Railway during coordination
4. **Consider adding WebSocket ping/pong** keepalive at application level
5. **Buffer events server-side** and replay on reconnect

## Potential Fixes

### Fix 1: Add Application-Level Keepalive
Send periodic ping messages to keep connection alive:
```python
async def keepalive_task(websocket, interval=15):
    while True:
        await asyncio.sleep(interval)
        await websocket.send_json({"type": "ping"})
```

### Fix 2: Event Replay on Reconnect
Buffer recent events and replay on WebSocket reconnect:
```python
# Server stores last N events per session
event_buffer[session_id].append(event)
# On reconnect, replay buffered events
```

### Fix 3: Increase Railway Timeout
Configure Railway to allow longer WebSocket connections (if possible via config).

### Fix 4: Use Server-Sent Events (SSE) as Fallback
SSE may be more reliable than WebSocket for one-way streaming.

## Related Files

- `massgen/frontend/web/server.py` - WebSocket handling
- `massgen/frontend/displays/web_display.py` - Event emission
- `docs/debugging-web-display-streaming.md` - General debugging guide
