# Current Issue: WebSocket Disconnects During Coordination

**Date:** 2026-01-03
**Status:** Partially Fixed (monitoring)

## Symptoms

1. **"WebSocket connection failed" banner** appears during coordination
2. **Agent cards stuck on "Waiting"** with "Answers: 0"
3. **"Coordination in progress..."** shown at bottom but no updates
4. Header shows **"Connected"** but error banner persists

## Console Logs

```
WebSocket disconnected: 1006
Reconnecting... Attempt 3/5
WebSocket connected
[DEBUG] WebSocket event: init Object   # <-- Problem: received "init" not "state_snapshot"
```

- **Code 1006** = Abnormal Closure (connection dropped without proper close frame)
- WebSocket reconnects but misses events during disconnect
- After reconnect, client receives `init` instead of `state_snapshot` (display not found)

## Root Cause Analysis (2026-01-03)

### Investigation Findings

1. **Server IS broadcasting correctly** - Railway logs confirmed:
   ```
   [Server] broadcast agent_content to 1 client(s)
   [WebDisplay] update_agent_content: agent=agent_a, type=thinking, len=26
   [Server] broadcast new_answer to 1 client(s)
   ```

2. **Problem is on reconnect** - Server checks if `display` exists for session:
   - If display exists → sends `state_snapshot` (full state recovery)
   - If display is None → sends `init` (no state, UI stays stale)

3. **Root cause**: After disconnect, `manager.get_display(session_id)` returns `None`
   - Possible reasons: session cleanup, different session ID, display not persisted

### Why Disconnects Happen

1. **Railway Proxy Timeout** - Railway's reverse proxy times out idle connections
   - Initial keepalive was 15 seconds - may be too long for Railway
   - Reduced to 10 seconds in fix

2. **Event gaps during LLM processing** - When agents are "thinking" there may be gaps
   between WebSocket messages, triggering proxy timeout

## Fixes Applied

### Fix 1: Application-Level Keepalive (Commit 98e16530)
Client sends ping every 15 seconds to keep connection alive:
```typescript
// webui/src/hooks/useWebSocket.ts
pingIntervalRef.current = setInterval(() => {
  if (ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ action: 'ping' }));
  }
}, PING_INTERVAL);
```

Server responds with pong:
```python
# server.py
elif action == "ping":
    await websocket.send_json({"type": "pong"})
```

### Fix 2: Reduced Ping Interval (Commit 96ce15d5)
Reduced ping interval from 15s to 10s - Railway may timeout faster:
```typescript
// webui/src/hooks/useWebSocket.ts
const PING_INTERVAL = 10000;  // Was 15000
```

### Fix 3: State Refresh on Reconnect (Commit 96ce15d5)
Client requests state refresh after reconnect to recover missed events:
```typescript
// webui/src/hooks/useWebSocket.ts
ws.onopen = () => {
  const wasReconnect = reconnectCountRef.current > 0;
  reconnectCountRef.current = 0;

  // If this was a reconnect, request current state to recover from missed events
  if (wasReconnect) {
    console.log('Reconnected - requesting state refresh');
    ws.send(JSON.stringify({ action: 'get_state' }));
  }
  // ...
};
```

## Remaining Issues

1. **Display may still be None** - If coordination finished or session was cleaned up,
   `get_state` action won't help. Need server-side event buffering.

2. **Events during disconnect are lost** - Current fix only recovers latest state,
   not streaming events missed during disconnect.

## Future Improvements

### Event Replay on Reconnect (Not Yet Implemented)
Buffer recent events and replay on WebSocket reconnect:
```python
# Server stores last N events per session
event_buffer[session_id].append(event)
# On reconnect, replay buffered events after state_snapshot
```

### Server-Sent Events (SSE) as Fallback
SSE may be more reliable than WebSocket for one-way streaming.

### Railway Configuration
Investigate if Railway allows configuring WebSocket timeout settings.

## Debug Logging

```python
# web_display.py - update_agent_content
print(f"[WebDisplay] update_agent_content: agent={agent_id}, type={content_type}, len={len(content)}", flush=True)

# server.py - broadcast
print(f"[Server] broadcast {msg_type} to {num_clients} client(s)", flush=True)
```

## Related Files

- `webui/src/hooks/useWebSocket.ts` - Client WebSocket handling & keepalive
- `massgen/frontend/web/server.py` - Server WebSocket handling & ping/pong
- `massgen/frontend/displays/web_display.py` - Event emission
- `docs/debugging-web-display-streaming.md` - General debugging guide

## Commits

- `98e16530` - Add WebSocket keepalive to prevent Railway proxy timeout
- `96ce15d5` - Fix WebSocket disconnect and state recovery
- `a3731b3b` - Fix React 18 batching causing UI to not update

---

# Additional Issue: UI Not Updating Despite WebSocket Events Arriving

**Date:** 2026-01-03
**Status:** Fixed

## Symptoms

1. Agent cards stuck on "Waiting..." even though coordination is in progress
2. WebSocket shows "Connected" and console logs show events arriving
3. UI only updates when browser extension interacts with the tab (screenshot/console read)
4. Clicking within the app does NOT trigger updates

## Root Cause

**React 18 Automatic Batching** - React 18 batches state updates by default for performance. WebSocket message handlers run outside React's event system, so state updates were being deferred indefinitely until something forced a repaint.

### Evidence

1. Console logs showed WebSocket events arriving: `coordination_started`, `preparation_status`, `init_status`
2. Zustand state was being updated (confirmed by state inspection)
3. React components were NOT re-rendering
4. Browser extension interaction (screenshot/console read) forced React to reconcile and render

### Why Browser Extension Interaction Fixed It

The Chrome extension's interaction with the tab likely triggered browser-level events (focus, visibility, or forced repaint) that caused React to flush pending state updates and re-render.

## Fix Applied

### flushSync Wrapper (Commit pending)

Wrap `processWSEvent` in React's `flushSync` to force synchronous rendering:

**File:** `webui/src/hooks/useWebSocket.ts`

```typescript
import { flushSync } from 'react-dom';

// Handle incoming messages
// Use flushSync to force immediate React re-renders on WebSocket events
// This prevents React 18's automatic batching from delaying UI updates
const handleMessage = useCallback(
  (event: MessageEvent) => {
    try {
      const data: WSEvent = JSON.parse(event.data);
      flushSync(() => {
        processWSEvent(data);
      });
    } catch (err) {
      console.error('Failed to parse WebSocket message:', err);
    }
  },
  [processWSEvent]
);
```

### Why This Works

- `flushSync` forces React to synchronously flush all pending updates
- WebSocket events now trigger immediate re-renders
- UI updates in real-time as events arrive

### Performance Consideration

Using `flushSync` for every WebSocket message may impact performance for high-frequency updates. If this becomes an issue, consider:

1. Debouncing/throttling UI updates
2. Only using `flushSync` for user-facing status changes
3. Batching multiple WebSocket events before flushing

## Related React 18 Documentation

- [React 18 Automatic Batching](https://react.dev/blog/2022/03/29/react-v18#new-feature-automatic-batching)
- [flushSync API](https://react.dev/reference/react-dom/flushSync)

## Files Modified

- `webui/src/hooks/useWebSocket.ts` - Added flushSync wrapper
