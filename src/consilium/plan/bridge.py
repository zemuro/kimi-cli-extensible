"""Bridge protocol for cross-references between Think and Do logs."""

from __future__ import annotations

from consilium.plan.log_entry import LogEntry, make_log_entry
from consilium.plan.persistent_log import PersistentLog


def append_bridge_out(
    think_log: PersistentLog,
    target_session_id: str,
    pushed_entry_ids: list[str],
    reason: str = "push_to_do",
) -> LogEntry:
    """Append a bridge_out entry to the Think log.

    Args:
        think_log: The Think-mode persistent log.
        target_session_id: The Do session being targeted.
        pushed_entry_ids: IDs of Think entries being pushed.
        reason: Human-readable reason for the bridge.
    """
    entry = make_log_entry(
        type="bridge_out",
        payload={
            "target_session_id": target_session_id,
            "pushed_entries": pushed_entry_ids,
            "reason": reason,
        },
        prev_id=think_log.tail_id(),
        log_owner="think",
    )
    think_log.append(entry)
    return entry


def append_bridge_in(
    do_log: PersistentLog,
    source_session_id: str,
    bridge_out_entry_id: str,
    source_message_ids: list[str],
) -> LogEntry:
    """Append a bridge_in entry to the Do log.

    Args:
        do_log: The Do-mode persistent log.
        source_session_id: The Think session that originated the push.
        bridge_out_entry_id: The ID of the bridge_out entry in the Think log.
        source_message_ids: IDs of messages seeded into Do context.
    """
    entry = make_log_entry(
        type="bridge_in",
        payload={
            "source_session_id": source_session_id,
            "source_entry": bridge_out_entry_id,
            "source_message_ids": source_message_ids,
        },
        prev_id=do_log.tail_id(),
        log_owner="do",
    )
    do_log.append(entry)
    return entry


def find_last_bridge_in_before(
    do_log: PersistentLog,
    before_entry_id: str,
) -> LogEntry | None:
    """Find the most recent bridge_in entry before a given entry."""
    before_idx = do_log._id_index.get(before_entry_id)
    if before_idx is None:
        return None

    bridges = do_log.find_entries_by_type("bridge_in")
    # Return the last bridge whose index is before before_idx
    candidate: LogEntry | None = None
    candidate_idx = -1
    for bridge in bridges:
        idx = do_log._id_index.get(bridge.id, -1)
        if idx < before_idx and idx > candidate_idx:
            candidate = bridge
            candidate_idx = idx
    return candidate


def trace_think_to_do(
    do_entry: LogEntry,
    do_log: PersistentLog,
    think_log: PersistentLog,
) -> list[LogEntry]:
    """Trace Think reasoning that led to a Do change.

    Returns the Think log entries that were pushed via the most recent
    bridge before the given Do entry.
    """
    bridge = find_last_bridge_in_before(do_log, do_entry.id)
    if not bridge:
        return []

    msg_ids = bridge.payload.get("source_message_ids", [])
    return [
        think_log.get_entry(mid)
        for mid in msg_ids
        if think_log.get_entry(mid) is not None
    ]


def trace_do_to_think(
    think_entry: LogEntry,
    think_log: PersistentLog,
    do_log: PersistentLog,
) -> list[LogEntry]:
    """Trace Do changes that resulted from a Think push.

    Returns Do log entries that occurred after the bridge_in that
    corresponds to the bridge_out nearest to the Think entry.
    """
    # Find the bridge_out entry nearest to think_entry
    entry_idx = think_log._id_index.get(think_entry.id)
    if entry_idx is None:
        return []

    bridges = think_log.find_entries_by_type("bridge_out")
    candidate: LogEntry | None = None
    candidate_idx = len(think_log.all_entries())
    for bridge in bridges:
        idx = think_log._id_index.get(bridge.id, -1)
        if idx >= entry_idx and idx < candidate_idx:
            candidate = bridge
            candidate_idx = idx

    if not candidate:
        return []

    # Find all do entries after the matching bridge_in
    do_bridges = do_log.find_entries_by_type("bridge_in")
    for do_bridge in do_bridges:
        if do_bridge.payload.get("source_entry") == candidate.id:
            # Return all do entries after this bridge_in
            bridge_idx = do_log._id_index.get(do_bridge.id, -1)
            return [
                e
                for e in do_log.all_entries()
                if do_log._id_index.get(e.id, -1) > bridge_idx
            ]

    return []
