# -*- coding: utf-8 -*-
"""
Web Display for MassGen Coordination

Implements BaseDisplay to broadcast coordination updates via WebSocket.
Provides real-time streaming to connected web clients.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional

from .base_display import BaseDisplay


class WebDisplay(BaseDisplay):
    """Display that streams updates to connected WebSocket clients.

    This class implements the BaseDisplay interface for web-based visualization.
    Instead of rendering to a terminal, it queues JSON events that are sent
    via WebSocket to connected browser clients.

    Args:
        agent_ids: List of agent identifiers
        broadcast: Async callable to send events to all connected clients
        session_id: Optional unique session identifier
        **kwargs: Additional configuration options
    """

    def __init__(
        self,
        agent_ids: List[str],
        broadcast: Optional[Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]] = None,
        session_id: Optional[str] = None,
        agent_models: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ):
        super().__init__(agent_ids, **kwargs)
        self._broadcast = broadcast
        self.session_id = session_id or "default"
        self.theme = kwargs.get("theme", "dark")
        self.agent_models = agent_models or {}

        # Event queue for when broadcast is not set (testing/standalone mode)
        self._event_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self._closed = False

        # Sequence number for ordering events
        self._sequence = 0

        # Track state for visualization
        self._vote_distribution: Dict[str, int] = {}
        self._vote_targets: Dict[str, str] = {}  # agent_id -> voted_for
        self._selected_agent: Optional[str] = None
        self._final_answer: Optional[str] = None

        # Timeline events for visualization (answers, votes, final with context sources)
        self._timeline_events: List[Dict[str, Any]] = []

        # Track file workspace changes per agent
        self._agent_files: Dict[str, List[Dict[str, Any]]] = {agent_id: [] for agent_id in agent_ids}

        # Orchestrator reference (set by CoordinationUI)
        self.orchestrator: Optional[Any] = None

        # Log session directory (set by _setup_agent_output_files, used by server API)
        self.log_session_dir: Optional[Path] = None

        # Setup agent output files (same as terminal displays)
        self._setup_agent_output_files()

    def _next_sequence(self) -> int:
        """Get next sequence number for event ordering."""
        self._sequence += 1
        return self._sequence

    def _emit(self, event_type: str, data: Dict[str, Any]) -> None:
        """Emit an event to connected clients.

        Args:
            event_type: Type of event (e.g., "agent_content", "agent_status")
            data: Event payload data
        """
        if self._closed:
            return

        payload = {
            "type": event_type,
            "session_id": self.session_id,
            "timestamp": time.time(),
            "sequence": self._next_sequence(),
            **data,
        }

        # If broadcast function is set, use it
        if self._broadcast is not None:
            try:
                # Create task to send event asynchronously
                asyncio.create_task(self._broadcast(payload))
            except RuntimeError:
                # No event loop running - queue the event instead
                self._event_queue.put_nowait(payload)
        else:
            # Queue for later consumption (testing/standalone mode)
            self._event_queue.put_nowait(payload)

    def _setup_agent_output_files(self) -> None:
        """Setup individual txt files for each agent in the log directory."""
        try:
            from massgen.logger_config import get_log_session_dir

            log_session_dir = get_log_session_dir()
            # Store for later access by the server API
            self.log_session_dir = log_session_dir
            if log_session_dir:
                self._output_dir = log_session_dir / "agent_outputs"
                self._output_dir.mkdir(parents=True, exist_ok=True)

                # Initialize file paths for each agent
                self._agent_output_files: Dict[str, Path] = {}
                for agent_id in self.agent_ids:
                    file_path = self._output_dir / f"{agent_id}.txt"
                    self._agent_output_files[agent_id] = file_path
                    # Clear existing file content
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(f"=== {agent_id.upper()} OUTPUT LOG ===\n\n")

                # Initialize system status file
                self._system_status_file = self._output_dir / "system_status.txt"
                with open(self._system_status_file, "w", encoding="utf-8") as f:
                    f.write("=== SYSTEM STATUS LOG ===\n\n")
            else:
                self._output_dir = None
                self._agent_output_files = {}
                self._system_status_file = None
        except Exception:
            # If logging setup fails, continue without file output
            self._output_dir = None
            self._agent_output_files = {}
            self._system_status_file = None

    def _write_to_agent_file(self, agent_id: str, content: str, content_type: str) -> None:
        """Write content to agent's individual txt file."""
        if not hasattr(self, "_agent_output_files") or agent_id not in self._agent_output_files:
            return

        # Skip debug content from txt files
        if content_type == "debug":
            return

        try:
            file_path = self._agent_output_files[agent_id]
            timestamp = time.strftime("%H:%M:%S")

            with open(file_path, "a", encoding="utf-8") as f:
                # Format based on content type
                if content_type in ("tool", "status"):
                    f.write(f"[{timestamp}] {content}\n")
                else:
                    f.write(f"{content}\n")
        except Exception:
            pass  # Silently ignore file write errors

    # =========================================================================
    # BaseDisplay Interface Implementation
    # =========================================================================

    def initialize(self, question: str, log_filename: Optional[str] = None) -> None:
        """Initialize the display with question and agent list.

        Args:
            question: The coordination question
            log_filename: Optional log file path
        """
        self.question = question  # Store for snapshot restoration

        # Print status.json location to terminal for automation monitoring
        # Use get_log_session_dir() to get the actual path with turn/attempt subdirectories
        try:
            from massgen.logger_config import get_log_session_dir

            log_session_dir = get_log_session_dir()
            if log_session_dir:
                print(f"[WebUI] LOG_DIR: {log_session_dir}")
                print(f"[WebUI] STATUS: {log_session_dir / 'status.json'}")
        except Exception:
            pass  # Silently ignore if logger not configured

        self._emit(
            "init",
            {
                "question": question,
                "log_filename": log_filename,
                "agents": self.agent_ids,
                "agent_models": self.agent_models,
                "theme": self.theme,
            },
        )

    def update_agent_content(
        self,
        agent_id: str,
        content: str,
        content_type: str = "thinking",
    ) -> None:
        """Stream content updates to a specific agent panel.

        Args:
            agent_id: The agent's identifier
            content: Content to append
            content_type: Type of content ("thinking", "tool", "status")
        """
        if agent_id not in self.agent_ids:
            return

        # Track content in parent class
        self.agent_outputs.setdefault(agent_id, []).append(content)

        # Write to agent output file
        self._write_to_agent_file(agent_id, content, content_type)

        self._emit(
            "agent_content",
            {
                "agent_id": agent_id,
                "content": content,
                "content_type": content_type,
            },
        )

    def update_agent_status(self, agent_id: str, status: str) -> None:
        """Update status for a specific agent.

        Args:
            agent_id: The agent's identifier
            status: New status ("waiting", "working", "voting", "completed")
        """
        if agent_id not in self.agent_ids:
            return

        # Track status in parent class
        self.agent_status[agent_id] = status

        self._emit(
            "agent_status",
            {
                "agent_id": agent_id,
                "status": status,
            },
        )

    def add_orchestrator_event(self, event: str) -> None:
        """Add an orchestrator coordination event.

        Args:
            event: The coordination event message
        """
        self.orchestrator_events.append(event)

        self._emit(
            "orchestrator_event",
            {
                "event": event,
            },
        )

    def stream_final_answer_chunk(
        self,
        chunk: str,
        selected_agent: Optional[str],
        vote_results: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Stream incoming final presentation content to the WebUI.

        This method is called during the final agent's streaming.
        On the FIRST chunk, it emits consensus_reached to trigger the
        finalStreaming view transition immediately.

        Args:
            chunk: Content chunk from the streaming response
            selected_agent: The agent selected as winner
            vote_results: Dictionary containing vote counts and details
        """
        if not chunk:
            return

        # On first chunk, emit consensus_reached to switch to finalStreaming view
        if not self._selected_agent and selected_agent:
            self._selected_agent = selected_agent
            if vote_results:
                self._vote_distribution = vote_results.get("vote_counts", {})

            # Update winner status to "working" since they're actively streaming
            # This overrides the earlier "completed" status from answer submission
            self._emit(
                "agent_status",
                {
                    "agent_id": selected_agent,
                    "status": "working",
                },
            )

            # Emit consensus_reached IMMEDIATELY when winner starts streaming
            self._emit(
                "consensus_reached",
                {
                    "winner_id": selected_agent,
                    "vote_distribution": self._vote_distribution,
                },
            )

        # Stream the content to the winning agent
        if selected_agent:
            self.update_agent_content(selected_agent, chunk, "thinking")

    def show_final_answer(
        self,
        answer: str,
        vote_results: Optional[Dict[str, Any]] = None,
        selected_agent: Optional[str] = None,
    ) -> None:
        """Display the final coordinated answer with convergence animation.

        Args:
            answer: The final coordinated answer
            vote_results: Dictionary containing vote counts and details
            selected_agent: The agent selected as winner
        """
        self._final_answer = answer
        should_emit_consensus = selected_agent and not self._selected_agent

        self._selected_agent = selected_agent

        # Extract vote distribution for visualization
        if vote_results:
            self._vote_distribution = vote_results.get("vote_counts", {})

        self._emit(
            "final_answer",
            {
                "answer": answer,
                "vote_results": vote_results or {},
                "selected_agent": selected_agent,
            },
        )

        # Only emit consensus_reached here if it wasn't already emitted by stream_final_answer_chunk
        # This handles the case where streaming didn't happen (e.g., cached answer)
        if should_emit_consensus:
            self._emit(
                "consensus_reached",
                {
                    "winner_id": selected_agent,
                    "vote_distribution": self._vote_distribution,
                },
            )

        # Record final answer for timeline visualization
        # Get context sources from iteration_available_labels (all answers used as input)
        if selected_agent:
            context_sources = []
            if self.orchestrator and hasattr(self.orchestrator, "coordination_tracker"):
                tracker = self.orchestrator.coordination_tracker
                context_sources = tracker.iteration_available_labels.copy()
            self.record_final_with_context(selected_agent, context_sources)

    def show_post_evaluation_content(self, content: str, agent_id: str) -> None:
        """Display post-evaluation streaming content.

        Args:
            content: Post-evaluation content from the agent
            agent_id: The agent performing the evaluation
        """
        self._emit(
            "post_evaluation",
            {
                "agent_id": agent_id,
                "content": content,
            },
        )

    def show_restart_banner(
        self,
        reason: str,
        instructions: str,
        attempt: int,
        max_attempts: int,
    ) -> None:
        """Display restart decision banner.

        Args:
            reason: Why the restart was triggered
            instructions: Instructions for the next attempt
            attempt: Next attempt number
            max_attempts: Maximum attempts allowed
        """
        self._emit(
            "restart",
            {
                "reason": reason,
                "instructions": instructions,
                "attempt": attempt,
                "max_attempts": max_attempts,
            },
        )

    def show_restart_context_panel(self, reason: str, instructions: str) -> None:
        """Display restart context panel at top of UI.

        Args:
            reason: Why the previous attempt restarted
            instructions: Instructions for this attempt
        """
        self._emit(
            "restart_context",
            {
                "reason": reason,
                "instructions": instructions,
            },
        )

    def cleanup(self) -> None:
        """Clean up display resources and signal session end."""
        self._emit(
            "done",
            {
                "final_status": {agent_id: self.agent_status.get(agent_id, "unknown") for agent_id in self.agent_ids},
            },
        )
        self._closed = True

    # =========================================================================
    # Web-Specific Methods (beyond BaseDisplay)
    # =========================================================================

    def update_vote_distribution(self, votes: Dict[str, int]) -> None:
        """Send vote distribution update for visualization.

        Args:
            votes: Dictionary mapping agent_id to vote count
        """
        self._vote_distribution = votes
        self._emit(
            "vote_distribution",
            {
                "votes": votes,
            },
        )

    def update_vote_target(self, voter_id: str, target_id: str, reason: str = "") -> None:
        """Record a vote cast by an agent.

        Args:
            voter_id: Agent who cast the vote
            target_id: Agent who received the vote
            reason: Reason for the vote
        """
        self._vote_targets[voter_id] = target_id
        self._emit(
            "vote_cast",
            {
                "voter_id": voter_id,
                "target_id": target_id,
                "reason": reason,
            },
        )

    # =========================================================================
    # Timeline Event Recording (for visualization)
    # =========================================================================

    def record_answer_with_context(
        self,
        agent_id: str,
        answer_label: str,
        context_sources: List[str],
        round_num: int,
    ) -> None:
        """Record an answer node with its context sources for timeline visualization.

        Args:
            agent_id: Agent who submitted the answer
            answer_label: Label like "answer1.1"
            context_sources: List of answer labels this agent saw (e.g., ["answer2.1"])
            round_num: Round number for this answer
        """
        self._timeline_events.append(
            {
                "id": f"{agent_id}-answer-{round_num}",
                "type": "answer",
                "agent_id": agent_id,
                "label": answer_label,
                "timestamp": time.time() * 1000,
                "round": round_num,
                "context_sources": context_sources,
            },
        )

    def record_vote_with_context(
        self,
        voter_id: str,
        vote_label: str,
        voted_for: str,
        available_answers: List[str],
    ) -> None:
        """Record a vote node with its available answers for timeline visualization.

        Args:
            voter_id: Agent who cast the vote
            vote_label: Label like "vote1.1"
            voted_for: Agent ID who received the vote
            available_answers: List of answer labels voter could see
        """
        self._timeline_events.append(
            {
                "id": f"{voter_id}-vote",
                "type": "vote",
                "agent_id": voter_id,
                "label": vote_label,
                "timestamp": time.time() * 1000,
                "round": 1,
                "context_sources": available_answers,
                "voted_for": voted_for,
            },
        )

    def record_final_with_context(
        self,
        agent_id: str,
        context_sources: List[str],
    ) -> None:
        """Record a final answer node with its context sources for timeline visualization.

        Args:
            agent_id: Winning agent who generated the final answer
            context_sources: List of answer labels used as input for final answer
        """
        self._timeline_events.append(
            {
                "id": f"{agent_id}-final",
                "type": "final",
                "agent_id": agent_id,
                "label": "final",
                "timestamp": time.time() * 1000,
                "round": 1,
                "context_sources": context_sources,
            },
        )

    def update_file_change(
        self,
        agent_id: str,
        path: str,
        operation: str,
        content: Optional[str] = None,
    ) -> None:
        """Notify about file changes in agent workspace.

        Args:
            agent_id: Agent whose workspace changed
            path: File path relative to workspace
            operation: "create", "modify", or "delete"
            content: Optional file content preview
        """
        file_info = {
            "path": path,
            "operation": operation,
            "timestamp": time.time(),
        }
        if content is not None:
            # Limit content preview size
            file_info["content_preview"] = content[:500] if len(content) > 500 else content

        self._agent_files[agent_id].append(file_info)

        self._emit(
            "file_change",
            {
                "agent_id": agent_id,
                **file_info,
            },
        )

    def highlight_winner(self, winner_id: str) -> None:
        """Trigger winner highlight animation.

        Args:
            winner_id: ID of the winning agent
        """
        self._emit(
            "winner_selected",
            {
                "winner_id": winner_id,
            },
        )

    def send_tool_call(
        self,
        agent_id: str,
        tool_name: str,
        tool_args: Dict[str, Any],
        tool_id: Optional[str] = None,
    ) -> None:
        """Notify about tool call execution.

        Args:
            agent_id: Agent making the tool call
            tool_name: Name of the tool being called
            tool_args: Arguments passed to the tool
            tool_id: Optional unique tool call ID
        """
        self._emit(
            "tool_call",
            {
                "agent_id": agent_id,
                "tool_name": tool_name,
                "tool_args": tool_args,
                "tool_id": tool_id,
            },
        )

    def send_tool_result(
        self,
        agent_id: str,
        tool_name: str,
        result: str,
        tool_id: Optional[str] = None,
        success: bool = True,
    ) -> None:
        """Notify about tool call result.

        Args:
            agent_id: Agent that made the tool call
            tool_name: Name of the tool
            result: Result from the tool
            tool_id: Optional tool call ID
            success: Whether the tool call succeeded
        """
        self._emit(
            "tool_result",
            {
                "agent_id": agent_id,
                "tool_name": tool_name,
                "result": result[:1000] if len(result) > 1000 else result,  # Limit size
                "tool_id": tool_id,
                "success": success,
            },
        )

    def send_error(self, message: str, agent_id: Optional[str] = None) -> None:
        """Send error notification.

        Args:
            message: Error message
            agent_id: Optional agent that caused the error
        """
        self._emit(
            "error",
            {
                "message": message,
                "agent_id": agent_id,
            },
        )

    def send_new_answer(
        self,
        agent_id: str,
        content: str,
        answer_id: Optional[str] = None,
        answer_number: int = 1,
    ) -> None:
        """Notify about a new answer from an agent.

        Args:
            agent_id: Agent that submitted the answer
            content: The answer content
            answer_id: Optional unique answer ID
            answer_number: The answer number for this agent (1, 2, etc.)
        """
        self._emit(
            "new_answer",
            {
                "agent_id": agent_id,
                "content": content,
                "answer_id": answer_id or f"{agent_id}-{int(time.time() * 1000)}",
                "answer_number": answer_number,
            },
        )

    # =========================================================================
    # Event Streaming (for standalone/testing mode)
    # =========================================================================

    async def stream_events(self):
        """Generator for SSE/WebSocket streaming when in standalone mode.

        Yields:
            JSON-encoded event strings
        """
        while not self._closed or not self._event_queue.empty():
            try:
                event = await asyncio.wait_for(
                    self._event_queue.get(),
                    timeout=30.0,  # Send keepalive every 30s
                )
                yield json.dumps(event)
            except asyncio.TimeoutError:
                # Send keepalive to keep connection alive
                yield json.dumps({"type": "keepalive", "timestamp": time.time()})

    def get_state_snapshot(self) -> Dict[str, Any]:
        """Get current display state for late-joining clients.

        Returns:
            Dictionary containing full current state
        """
        return {
            "session_id": self.session_id,
            "question": getattr(self, "question", ""),
            "agents": self.agent_ids,
            "agent_models": self.agent_models,
            "agent_status": dict(self.agent_status),
            "agent_outputs": {agent_id: list(outputs) for agent_id, outputs in self.agent_outputs.items()},
            "vote_distribution": dict(self._vote_distribution),
            "vote_targets": dict(self._vote_targets),
            "selected_agent": self._selected_agent,
            "final_answer": self._final_answer,
            "orchestrator_events": list(self.orchestrator_events),
            "theme": self.theme,
        }


def is_web_display_available() -> bool:
    """Check if web display dependencies are available.

    Returns:
        True if FastAPI and uvicorn are installed
    """
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401

        return True
    except ImportError:
        return False
