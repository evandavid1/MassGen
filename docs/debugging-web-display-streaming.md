# Debugging Web Display Streaming Issues

This document covers how to diagnose issues where agent cards/panes don't update in real-time on the MassGen web UI.

## Symptoms

- Agent cards show "Waiting" status even though coordination is running
- Cards don't show streaming content (thinking, tool calls, answers)
- Final answer appears but intermediate updates don't
- Works locally but not on Railway/production

## Architecture Overview

The streaming pipeline:

```
Orchestrator.chat()
    → yields StreamChunk(type="content", source=agent_id)
        → CoordinationUI._process_content(source, content)
            → CoordinationUI._process_agent_content(agent_id, content)
                → WebDisplay.update_agent_content(agent_id, content, content_type)
                    → WebDisplay._emit("agent_content", {...})
                        → asyncio.create_task(broadcast(payload))
                            → WebSocket.send_json(message)
                                → Frontend JavaScript handles event
```

## Key Event Types

| Event Type | Purpose | When Sent |
|------------|---------|-----------|
| `init` | Initialize session with agents | Session start |
| `preparation_status` | Setup progress updates | During agent initialization |
| `agent_status` | Agent state changes | waiting/working/completed transitions |
| `agent_content` | Streaming thinking content | During agent processing |
| `new_answer` | Agent submitted an answer | When agent calls new_answer tool |
| `orchestrator_event` | Coordination events | Votes, consensus, etc. |
| `final_answer` | Final coordinated answer | End of coordination |

## Debugging Steps

### 1. Check Browser Console

Open DevTools (F12) and look for WebSocket events:

```javascript
// These should appear in console
[DEBUG] WebSocket connected
[DEBUG] WebSocket event: init Object
[DEBUG] WebSocket event: agent_status Object
[DEBUG] WebSocket event: agent_content Object  // <-- Key for streaming
[DEBUG] WebSocket event: new_answer Object
```

**If you see `init` but not `agent_content`:** The issue is server-side (events not being emitted).

**If you see no WebSocket events:** Connection issue - check auth or network.

### 2. Add Server-Side Debug Logging

Add to `massgen/frontend/displays/web_display.py`:

```python
def update_agent_content(self, agent_id: str, content: str, content_type: str = "thinking") -> None:
    # DEBUG: Log all calls
    print(f"[WebDisplay DEBUG] update_agent_content: agent_id='{agent_id}', type='{content_type}'", flush=True)
    print(f"[WebDisplay DEBUG] self.agent_ids = {self.agent_ids}", flush=True)

    if agent_id not in self.agent_ids:
        print(f"[WebDisplay DEBUG] SKIPPING - agent_id not in agent_ids!", flush=True)
        return

    print(f"[WebDisplay DEBUG] EMITTING agent_content for {agent_id}", flush=True)
    # ... rest of method
```

Add to `_emit` method:

```python
def _emit(self, event_type: str, data: Dict[str, Any]) -> None:
    print(f"[WebDisplay DEBUG] _emit: type={event_type}, has_broadcast={self._broadcast is not None}", flush=True)
    # ... rest of method
```

Add to `massgen/frontend/web/server.py` broadcast function:

```python
async def broadcast(self, session_id: str, message: Dict[str, Any]) -> None:
    msg_type = message.get("type", "unknown")
    print(f"[Server DEBUG] broadcast: session={session_id}, type={msg_type}", flush=True)

    if session_id not in self.active_connections:
        print(f"[Server DEBUG] No active connections for {session_id}", flush=True)
        return

    print(f"[Server DEBUG] Broadcasting to {len(self.active_connections[session_id])} clients", flush=True)
    # ... rest of method
```

### 3. Common Issues and Solutions

#### Issue: Agent ID Mismatch

**Symptom:** Logs show `SKIPPING - agent_id not in agent_ids`

**Cause:** The `agent_id` in streaming chunks doesn't match what WebDisplay was initialized with.

**Fix:** Ensure agent IDs are consistent between:
- `create_agents_from_config()` returns
- `WebDisplay(agent_ids=...)` initialization
- `CoordinationUI.agent_ids` assignment

#### Issue: No Broadcast Function

**Symptom:** Logs show `No broadcast function, queuing`

**Cause:** WebDisplay was created without the broadcast callback.

**Fix:** Ensure web server passes broadcast function:
```python
display = WebDisplay(
    agent_ids=agent_ids,
    broadcast=broadcast_fn,  # Must not be None
    session_id=session_id,
)
```

#### Issue: No Active WebSocket Connections

**Symptom:** Logs show `No active connections for session`

**Cause:** WebSocket disconnected before/during coordination.

**Fix:**
- Check for WebSocket disconnection in browser console
- Verify HTTP Basic Auth is working for WebSocket (code 4001 = auth failed)
- Check Railway proxy timeout settings

#### Issue: asyncio Task Not Running

**Symptom:** `_emit` is called but broadcast never happens

**Cause:** `asyncio.create_task()` fails silently when no event loop is running.

**Fix:** The code catches `RuntimeError` and queues events, but verify the event loop is active during coordination.

### 4. Railway-Specific Issues

#### WebSocket Timeout

Railway's reverse proxy may timeout idle WebSocket connections. Events might batch up and arrive late.

**Solution:** The app sends keepalive pings, but verify they're working.

#### Print Buffering

Python's `print()` may be buffered on Railway.

**Solution:** Always use `flush=True`:
```python
print("message", flush=True)
```

#### Build Cache

Old code might be cached.

**Solution:** In Railway dashboard, trigger a fresh deploy or clear build cache.

### 5. Verify Event Flow

Run a test and check logs for this sequence:

```
[WebDisplay DEBUG] update_agent_content: agent_id='agent_a'
[WebDisplay DEBUG] self.agent_ids = ['agent_a', 'agent_b', 'agent_c']
[WebDisplay DEBUG] EMITTING agent_content for agent_a
[WebDisplay DEBUG] _emit: type=agent_content, has_broadcast=True
[Server DEBUG] broadcast: session=xxx, type=agent_content
[Server DEBUG] Broadcasting to 1 clients
```

If any step is missing, the issue is at that point in the pipeline.

## What Updates the Agent Cards

The agent cards can update through multiple event types:

1. **`agent_content`** - Real-time streaming of thinking/reasoning (may not always be sent)
2. **`agent_status`** - Status badge changes (waiting/working/completed)
3. **`new_answer`** - When agent submits an answer (updates answer count and content)
4. **`orchestrator_event`** - Coordination events (votes, etc.)

If `agent_content` events aren't showing but cards still update with answers, the system is working - just not streaming intermediate content.

## Removing Debug Logging

Once the issue is resolved, remove or comment out the debug print statements to reduce log noise:

```bash
# Search for debug statements
grep -r "WebDisplay DEBUG\|Server DEBUG" massgen/
```

## Related Files

- `massgen/frontend/displays/web_display.py` - WebDisplay class
- `massgen/frontend/web/server.py` - FastAPI server and WebSocket handling
- `massgen/frontend/coordination_ui.py` - CoordinationUI stream processing
- `massgen/orchestrator.py` - Orchestrator streaming chunks
