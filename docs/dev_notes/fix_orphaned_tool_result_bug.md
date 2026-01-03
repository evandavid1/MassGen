# Bug Fix: Orphaned tool_result Blocks Causing Claude API Error

## Issue Summary

Claude Opus 4.5 agents were failing with the following error during multi-agent coordination:

```
Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error',
'message': 'messages.2.content.0: unexpected `tool_use_id` found in `tool_result`
blocks: toolu_01Y2JVtmvedxpbbcQBe1XKwX. Each `tool_result` block must have a
corresponding `tool_use` block in the previous message.'}}
```

This error only occurred on Claude Opus 4.5 agents during specific race conditions when:
1. The agent was voting for another agent's answer
2. Another agent finished providing an answer (triggering `restart_pending`)
3. The orchestrator attempted to inject an update

## Root Cause Analysis

### The Bug Location

In `massgen/orchestrator.py` around line 4217-4232, the `vote` tool handling had a control flow bug:

```python
if tool_name == "vote":
    # ... logging ...
    if self._check_restart_pending(agent_id):
        should_continue = await self._inject_update_and_continue(...)
        if should_continue:
            yield ("content", f"📨 [{agent_id}] receiving update with new answers\n")
            continue  # <-- BUG: This continues INNER loop, skipping workflow_tool_found
    workflow_tool_found = True  # <-- NEVER executed when continue is taken
```

### The Problem

1. **Agent votes** - The agent uses the `vote` workflow tool
2. **Restart pending check** - `_check_restart_pending()` returns True (another agent finished)
3. **Update injection** - `_inject_update_and_continue()` injects update and returns True
4. **`continue` is executed** - BUT it only continues the inner `for tool_call in tool_calls:` loop
5. **`workflow_tool_found = True` is SKIPPED** - This line comes after the `continue`
6. **Enforcement triggers** - After the inner loop, `if not workflow_tool_found:` evaluates to True
7. **Error messages created** - `_create_tool_error_messages()` creates `tool_result` blocks referencing the vote's `tool_use_id`
8. **Next iteration fails** - The `tool_result` blocks don't have matching `tool_use` blocks in the agent's conversation history
9. **Claude API rejects** - The API returns the "unexpected tool_use_id" error

### Why Only Claude Opus 4.5?

This was a race condition that was more likely to occur with slower models (Opus 4.5) where:
- The agent takes longer to complete its response
- Other faster agents (e.g., Sonnet) finish first and trigger the restart_pending flag
- The timing window for the bug to manifest is larger

## The Fix

Set `workflow_tool_found = True` **BEFORE** any early exit (`continue`) statements in the vote handling block:

```python
if tool_name == "vote":
    # Log which agents we are choosing from
    logger.info(...)
    # Mark vote as workflow tool BEFORE any early exits
    # This prevents false "needs to use workflow tools" enforcement
    workflow_tool_found = True  # <-- MOVED HERE
    # Check if agent should restart - votes invalid during restart
    if self._check_restart_pending(agent_id):
        should_continue = await self._inject_update_and_continue(...)
        if should_continue:
            yield ("content", f"📨 [{agent_id}] receiving update with new answers\n")
            continue  # Now workflow_tool_found is already True
```

This matches the pattern already used for `new_answer` handling (line 4324), where `workflow_tool_found = True` is set at the start of the block.

## Files Changed

- `massgen/orchestrator.py`: Moved `workflow_tool_found = True` before the early exit logic in vote handling

## Testing

The fix prevents the enforcement logic from triggering when the agent has already used a workflow tool (vote). Even if the inner loop continues, the `workflow_tool_found` flag is properly set, so the "Case 3: Non-workflow response" block (line 4477) is not entered.

---

## PR Details

### Title
fix: Set workflow_tool_found before early exit in vote handling

### Description
Fixes a race condition bug where Claude Opus 4.5 agents would fail with "unexpected tool_use_id found in tool_result blocks" during multi-agent coordination.

**Root Cause:** When an agent voted while another agent was finishing, the orchestrator would inject an update and `continue` the inner tool loop. However, `workflow_tool_found = True` was set *after* the `continue` statement, causing it to be skipped. This led to false enforcement logic triggering, which created tool_result messages without matching tool_use blocks.

**Fix:** Move `workflow_tool_found = True` to the start of the vote handling block, before any `continue` statements. This matches the existing pattern used for `new_answer` handling.

### Labels
- bug
- orchestrator
- claude

### Related Issues
None

### Checklist
- [x] Code change is minimal and focused
- [x] Follows existing code patterns (`new_answer` handling)
- [x] No new dependencies
- [x] Fixes the specific race condition
