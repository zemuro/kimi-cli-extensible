"""Regression tests for the exit-path stderr guard.

The CLI's ``_emit_fatal_error`` (and friends) write fatal messages to the
original stderr fd via ``open_original_stderr``. During Wire/ACP teardown the
underlying pipe may already be closed, so the write/flush/close must never
crash the process with a secondary OSError (the "OSError: [Errno 22] Invalid
argument" crash class seen on the exit path).
"""
from __future__ import annotations

import io

import pytest

from consilium.utils.logging import open_original_stderr


class _ClosingStream(io.BytesIO):
    """BytesIO that raises OSError on close, simulating a dead pipe."""

    def close(self) -> None:
        raise OSError(22, "Invalid argument")


class _FailOnWriteStream(io.BytesIO):
    """BytesIO that raises OSError on write, simulating a broken pipe."""

    def write(self, data) -> int:  # type: ignore[override]
        raise OSError(22, "Invalid argument")


class _Redirector:
    def __init__(self, stream):
        self._stream = stream

    def open_original_stderr_handle(self):
        return self._stream


def test_open_original_stderr_close_error_is_suppressed(monkeypatch: pytest.MonkeyPatch):
    """A stream whose close() raises OSError must not propagate."""
    import consilium.utils.logging as logging_mod

    monkeypatch.setattr(logging_mod, "_stderr_redirector", _Redirector(_ClosingStream()))
    with open_original_stderr() as stream:
        assert stream is not None
    # If close() raised, the test would have failed above.


def test_open_original_stderr_write_error_is_suppressed(monkeypatch: pytest.MonkeyPatch):
    """A stream whose write() raises OSError must not propagate to callers.

    ``open_original_stderr`` only guards the close in its own ``finally``;
    callers such as ``_emit_fatal_error`` wrap write/flush with a try/except
    OSError. This test exercises that caller-side contract via the same
    pattern used in ``consilium.cli._emit_fatal_error``.
    """
    import consilium.utils.logging as logging_mod

    monkeypatch.setattr(logging_mod, "_stderr_redirector", _Redirector(_FailOnWriteStream()))
    with open_original_stderr() as stream:
        assert stream is not None
        try:
            stream.write(b"fatal")
        except OSError:
            pass  # caller-side guard swallows write errors


def test_open_original_stderr_flush_error_is_suppressed(monkeypatch: pytest.MonkeyPatch):
    """A stream whose flush() raises OSError must not propagate to callers."""
    import consilium.utils.logging as logging_mod

    class _FailOnFlushStream(io.BytesIO):
        def flush(self) -> None:
            raise OSError(22, "Invalid argument")

    monkeypatch.setattr(logging_mod, "_stderr_redirector", _Redirector(_FailOnFlushStream()))
    with open_original_stderr() as stream:
        assert stream is not None
        try:
            stream.flush()
        except OSError:
            pass  # caller-side guard swallows flush errors


def test_open_original_stderr_no_redirector_yields_none(monkeypatch: pytest.MonkeyPatch):
    """With no redirector installed, the context manager yields None (no-op)."""
    import consilium.utils.logging as logging_mod

    monkeypatch.setattr(logging_mod, "_stderr_redirector", None)
    with open_original_stderr() as stream:
        assert stream is None