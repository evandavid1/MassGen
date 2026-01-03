# PR: Fix WebUI Not Updating on WebSocket Events

## Summary

Fixes an issue where the WebUI agent cards would show "Waiting..." indefinitely even though WebSocket events were arriving and state was being updated correctly. The UI would only update when an external event (like browser dev tools interaction) forced a repaint.

## Problem

### Root Cause: React 18 Automatic Batching

React 18 introduced automatic batching which defers state updates for performance. However, state updates triggered from WebSocket message handlers run outside React's event system, causing them to be batched indefinitely until something forces a repaint.

**Symptoms:**
- Agent cards stuck on "Waiting..." with "Answers: 0"
- "Coordination in progress..." shown but no updates
- Console logs show WebSocket events arriving correctly
- Zustand state is updated correctly
- UI only updates when browser is externally triggered (dev tools, tab switch, etc.)

### Secondary Issue: WebSocket Disconnects on Hosted Deployments

When deployed behind reverse proxies (Railway, Heroku, etc.), idle WebSocket connections can be terminated by proxy timeout, causing:
- WebSocket disconnect code 1006 (abnormal closure)
- Missed events during disconnect
- State desync after reconnect

## Solution

### Fix 1: Force Synchronous Rendering with flushSync

Wrap WebSocket message processing in React's `flushSync` to force immediate re-renders:

```typescript
// webui/src/hooks/useWebSocket.ts
import { flushSync } from 'react-dom';

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

### Fix 2: Application-Level Keepalive

Client sends ping every 10 seconds to prevent proxy timeout:

```typescript
// webui/src/hooks/useWebSocket.ts
const PING_INTERVAL = 10000;

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

### Fix 3: State Recovery on Reconnect

Request current state after reconnecting to recover from missed events:

```typescript
// webui/src/hooks/useWebSocket.ts
ws.onopen = () => {
  const wasReconnect = reconnectCountRef.current > 0;
  reconnectCountRef.current = 0;

  if (wasReconnect) {
    console.log('Reconnected - requesting state refresh');
    ws.send(JSON.stringify({ action: 'get_state' }));
  }
  // ...
};
```

## Files Changed

- `webui/src/hooks/useWebSocket.ts` - All three fixes
- `massgen/frontend/web/server.py` - Ping/pong handler (if not already present)

## Testing

1. Start coordination via WebUI
2. Verify agent cards update in real-time as events arrive
3. Verify UI continues updating without needing to interact with browser
4. Test WebSocket reconnection by temporarily disconnecting network
5. Verify state recovers correctly after reconnect

## Performance Consideration

Using `flushSync` for every WebSocket message ensures immediate UI updates but may impact performance for very high-frequency updates. If this becomes an issue, consider:

1. Debouncing/throttling UI updates
2. Only using `flushSync` for user-facing status changes
3. Batching multiple WebSocket events before flushing

In practice, MassGen's event frequency is low enough that this should not be a concern.

## Related

- [React 18 Automatic Batching](https://react.dev/blog/2022/03/29/react-v18#new-feature-automatic-batching)
- [flushSync API](https://react.dev/reference/react-dom/flushSync)
