/**
 * WebSocket Hook for MassGen Real-Time Communication
 *
 * Manages WebSocket connection lifecycle, auto-reconnection,
 * and event processing.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { flushSync } from 'react-dom';
import { useAgentStore } from '../stores/agentStore';
import type { WSEvent } from '../types';

export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'error';

interface UseWebSocketOptions {
  sessionId: string;
  autoConnect?: boolean;
  reconnectAttempts?: number;
  reconnectInterval?: number;
}

interface UseWebSocketReturn {
  status: ConnectionStatus;
  connect: () => void;
  disconnect: () => void;
  send: (data: Record<string, unknown>) => void;
  startCoordination: (question: string, configPath?: string) => void;
  continueConversation: (question: string) => void;
  cancelCoordination: () => void;
  error: string | null;
}

export function useWebSocket({
  sessionId,
  autoConnect = true,
  reconnectAttempts = 5,
  reconnectInterval = 3000,
}: UseWebSocketOptions): UseWebSocketReturn {
  const [status, setStatus] = useState<ConnectionStatus>('disconnected');
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectCountRef = useRef(0);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pingIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Keepalive interval (10 seconds) - prevents Railway proxy timeout
  // Railway's proxy may timeout connections faster than 15 seconds
  const PING_INTERVAL = 10000;

  const processWSEvent = useAgentStore((state) => state.processWSEvent);

  // Build WebSocket URL
  const getWsUrl = useCallback(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    return `${protocol}//${host}/ws/${sessionId}`;
  }, [sessionId]);

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

  // Connect to WebSocket
  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    setStatus('connecting');
    setError(null);

    try {
      const ws = new WebSocket(getWsUrl());

      ws.onopen = () => {
        setStatus('connected');
        setError(null); // Clear any stale error on successful connection
        const wasReconnect = reconnectCountRef.current > 0;
        reconnectCountRef.current = 0;
        console.log('WebSocket connected');

        // If this was a reconnect, request current state to recover from missed events
        if (wasReconnect) {
          console.log('Reconnected - requesting state refresh');
          ws.send(JSON.stringify({ action: 'get_state' }));
        }

        // Start keepalive pings to prevent proxy timeout
        if (pingIntervalRef.current) {
          clearInterval(pingIntervalRef.current);
        }
        pingIntervalRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ action: 'ping' }));
          }
        }, PING_INTERVAL);
      };

      ws.onmessage = handleMessage;

      ws.onclose = (event) => {
        setStatus('disconnected');
        console.log('WebSocket disconnected:', event.code, event.reason);

        // Stop keepalive pings
        if (pingIntervalRef.current) {
          clearInterval(pingIntervalRef.current);
          pingIntervalRef.current = null;
        }

        // Auto-reconnect if not intentionally closed
        if (event.code !== 1000 && reconnectCountRef.current < reconnectAttempts) {
          reconnectCountRef.current++;
          console.log(
            `Reconnecting... Attempt ${reconnectCountRef.current}/${reconnectAttempts}`
          );

          reconnectTimeoutRef.current = setTimeout(() => {
            connect();
          }, reconnectInterval);
        }
      };

      ws.onerror = (event) => {
        console.error('WebSocket error:', event);
        setStatus('error');
        setError('WebSocket connection failed');
      };

      wsRef.current = ws;
    } catch (err) {
      console.error('Failed to create WebSocket:', err);
      setStatus('error');
      setError(err instanceof Error ? err.message : 'Failed to connect');
    }
  }, [getWsUrl, handleMessage, reconnectAttempts, reconnectInterval]);

  // Disconnect from WebSocket
  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    // Stop keepalive pings
    if (pingIntervalRef.current) {
      clearInterval(pingIntervalRef.current);
      pingIntervalRef.current = null;
    }

    if (wsRef.current) {
      wsRef.current.close(1000, 'Client disconnect');
      wsRef.current = null;
    }

    setStatus('disconnected');
  }, []);

  // Send message via WebSocket
  const send = useCallback((data: Record<string, unknown>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
    } else {
      console.warn('WebSocket is not connected');
    }
  }, []);

  // Start coordination
  const startCoordination = useCallback(
    (question: string, configPath?: string) => {
      send({
        action: 'start',
        question,
        config: configPath,
      });
    },
    [send]
  );

  // Continue conversation with follow-up question
  const continueConversation = useCallback(
    (question: string) => {
      send({
        action: 'continue',
        question,
      });
    },
    [send]
  );

  // Cancel coordination
  const cancelCoordination = useCallback(() => {
    send({
      action: 'cancel',
    });
  }, [send]);

  // Auto-connect on mount
  useEffect(() => {
    if (autoConnect && sessionId) {
      connect();
    }

    return () => {
      disconnect();
    };
  }, [autoConnect, sessionId, connect, disconnect]);

  return {
    status,
    connect,
    disconnect,
    send,
    startCoordination,
    continueConversation,
    cancelCoordination,
    error,
  };
}

export default useWebSocket;
