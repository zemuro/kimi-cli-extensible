"""Module-level registry for active Do mode sessions."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from consilium.do.session import DoSession

_DO_SESSIONS: dict[str, DoSession] = {}


def register_do_session(session_id: str, do_session: DoSession) -> None:
    _DO_SESSIONS[session_id] = do_session


def get_do_session(session_id: str) -> DoSession | None:
    return _DO_SESSIONS.get(session_id)


def unregister_do_session(session_id: str) -> None:
    _DO_SESSIONS.pop(session_id, None)
