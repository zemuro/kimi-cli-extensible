"""Tests for Phase 5A wire protocol query handlers."""

from __future__ import annotations

from pathlib import Path

import pytest
from kosong.tooling.empty import EmptyToolset

from consilium.plan.bridge import append_bridge_in, append_bridge_out
from consilium.plan.log_entry import make_log_entry
from consilium.plan.persistent_log import PersistentLog
from consilium.soul.agent import Agent, Runtime
from consilium.soul.context import Context
from consilium.soul.consiliumsoul import ConsiliumSoul
from consilium.wire.jsonrpc import (
    ErrorCodes,
    JSONRPCErrorResponse,
    JSONRPCLogQueryMessage,
    JSONRPCPlanFetchMessage,
    JSONRPCQuotaMessage,
    JSONRPCSuccessResponse,
    JSONRPCTraceMessage,
)
from consilium.wire.server import WireServer


@pytest.fixture(autouse=True)
def _patch_log_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch PersistentLog.for_session to use tmp_path instead of ~/.consilium/."""

    def _patched_for_session(session_id: str, log_owner: str) -> PersistentLog:
        log_dir = tmp_path / f"{log_owner}_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        return PersistentLog(log_dir / f"{session_id}.jsonl", log_owner=log_owner)

    monkeypatch.setattr(PersistentLog, "for_session", _patched_for_session)


def _make_soul(runtime: Runtime, tmp_path: Path) -> ConsiliumSoul:
    agent = Agent(
        name="Query Test Agent",
        system_prompt="Test prompt.",
        toolset=EmptyToolset(),
        runtime=runtime,
    )
    return ConsiliumSoul(agent, context=Context(file_backend=tmp_path / "history.jsonl"))


class TestHandleLogQuery:
    @pytest.mark.asyncio
    async def test_returns_entries(self, runtime: Runtime, tmp_path: Path) -> None:
        soul = _make_soul(runtime, tmp_path)
        server = WireServer(soul)

        log = PersistentLog.for_session("test-session", "think")
        e1 = make_log_entry("message", {"role": "user", "content": "hello"}, None, "think")
        e2 = make_log_entry("message", {"role": "assistant", "content": "hi"}, e1.id, "think")
        log.append(e1)
        log.append(e2)

        msg = JSONRPCLogQueryMessage(
            id="1",
            params=JSONRPCLogQueryMessage.Params(
                session_id="test-session",
                log_owner="think",
            ),
        )
        resp = await server._handle_log_query(msg)
        assert isinstance(resp, JSONRPCSuccessResponse)
        assert len(resp.result["entries"]) == 2
        assert resp.result["has_more"] is False

    @pytest.mark.asyncio
    async def test_pagination(self, runtime: Runtime, tmp_path: Path) -> None:
        soul = _make_soul(runtime, tmp_path)
        server = WireServer(soul)

        log = PersistentLog.for_session("test-session", "think")
        for i in range(5):
            prev = log.tail_id()
            e = make_log_entry("message", {"role": "user", "content": f"msg{i}"}, prev, "think")
            log.append(e)

        msg = JSONRPCLogQueryMessage(
            id="1",
            params=JSONRPCLogQueryMessage.Params(
                session_id="test-session",
                log_owner="think",
                limit=2,
            ),
        )
        resp = await server._handle_log_query(msg)
        assert isinstance(resp, JSONRPCSuccessResponse)
        assert len(resp.result["entries"]) == 2
        assert resp.result["has_more"] is True

    @pytest.mark.asyncio
    async def test_filter_by_type(self, runtime: Runtime, tmp_path: Path) -> None:
        soul = _make_soul(runtime, tmp_path)
        server = WireServer(soul)

        log = PersistentLog.for_session("test-session", "do")
        e1 = make_log_entry("diff", {"path": "a.py"}, None, "do")
        e2 = make_log_entry("review", {"approved": True}, e1.id, "do")
        e3 = make_log_entry("diff", {"path": "b.py"}, e2.id, "do")
        log.append(e1)
        log.append(e2)
        log.append(e3)

        msg = JSONRPCLogQueryMessage(
            id="1",
            params=JSONRPCLogQueryMessage.Params(
                session_id="test-session",
                log_owner="do",
                filter_type="diff",
            ),
        )
        resp = await server._handle_log_query(msg)
        assert isinstance(resp, JSONRPCSuccessResponse)
        assert len(resp.result["entries"]) == 2
        assert all(e["type"] == "diff" for e in resp.result["entries"])

    @pytest.mark.asyncio
    async def test_after_id(self, runtime: Runtime, tmp_path: Path) -> None:
        soul = _make_soul(runtime, tmp_path)
        server = WireServer(soul)

        log = PersistentLog.for_session("test-session", "think")
        e1 = make_log_entry("message", {"role": "user", "content": "first"}, None, "think")
        e2 = make_log_entry("message", {"role": "user", "content": "second"}, e1.id, "think")
        e3 = make_log_entry("message", {"role": "user", "content": "third"}, e2.id, "think")
        log.append(e1)
        log.append(e2)
        log.append(e3)

        msg = JSONRPCLogQueryMessage(
            id="1",
            params=JSONRPCLogQueryMessage.Params(
                session_id="test-session",
                log_owner="think",
                after_id=e1.id,
            ),
        )
        resp = await server._handle_log_query(msg)
        assert isinstance(resp, JSONRPCSuccessResponse)
        assert len(resp.result["entries"]) == 2

    @pytest.mark.asyncio
    async def test_invalid_params(self, runtime: Runtime, tmp_path: Path) -> None:
        soul = _make_soul(runtime, tmp_path)
        server = WireServer(soul)

        msg = JSONRPCLogQueryMessage(
            id="1",
            params=JSONRPCLogQueryMessage.Params(
                session_id="",
                log_owner="think",
            ),
        )
        resp = await server._handle_log_query(msg)
        assert isinstance(resp, JSONRPCErrorResponse)
        assert resp.error.code == ErrorCodes.INVALID_PARAMS


class TestHandlePlanFetch:
    @pytest.mark.asyncio
    async def test_returns_content_and_parsed(self, runtime: Runtime, tmp_path: Path) -> None:
        soul = _make_soul(runtime, tmp_path)
        server = WireServer(soul)

        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        index = plan_dir / "index.md"
        index.write_text(
            "---\nplan_id: test-plan\n---\n\n# Plan\n\n"
            "| Phase | Title | Status |\n"
            "|-------|-------|--------|\n"
            "| phase-01 | Setup | implemented |\n",
            encoding="utf-8",
        )
        (plan_dir / "phase-01.md").write_text(
            "---\nphase_id: phase-01\ntitle: Setup\nstatus: implemented\n---\n\nSetup phase.\n",
            encoding="utf-8",
        )

        # Override work_dir so resolution works
        soul.runtime.session.work_dir = tmp_path

        msg = JSONRPCPlanFetchMessage(
            id="1",
            params=JSONRPCPlanFetchMessage.Params(plan_file="plan/index.md"),
        )
        resp = await server._handle_plan_fetch(msg)
        assert isinstance(resp, JSONRPCSuccessResponse)
        assert "# Plan" in resp.result["content"]
        assert resp.result["parsed"] is not None
        assert len(resp.result["parsed"]["phases"]) == 1
        assert resp.result["parsed"]["phases"][0]["phase_id"] == "phase-01"

    @pytest.mark.asyncio
    async def test_non_index_file(self, runtime: Runtime, tmp_path: Path) -> None:
        soul = _make_soul(runtime, tmp_path)
        server = WireServer(soul)

        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        phase_file = plan_dir / "phase-01.md"
        phase_file.write_text("# Phase 1\n\nDetails.\n", encoding="utf-8")

        soul.runtime.session.work_dir = tmp_path

        msg = JSONRPCPlanFetchMessage(
            id="1",
            params=JSONRPCPlanFetchMessage.Params(plan_file="plan/phase-01.md"),
        )
        resp = await server._handle_plan_fetch(msg)
        assert isinstance(resp, JSONRPCSuccessResponse)
        assert resp.result["content"] == "# Phase 1\n\nDetails.\n"
        assert resp.result["parsed"] is None

    @pytest.mark.asyncio
    async def test_path_traversal(self, runtime: Runtime, tmp_path: Path) -> None:
        soul = _make_soul(runtime, tmp_path)
        server = WireServer(soul)

        soul.runtime.session.work_dir = tmp_path

        msg = JSONRPCPlanFetchMessage(
            id="1",
            params=JSONRPCPlanFetchMessage.Params(plan_file="../etc/passwd"),
        )
        resp = await server._handle_plan_fetch(msg)
        assert isinstance(resp, JSONRPCErrorResponse)
        assert resp.error.code == ErrorCodes.INVALID_PARAMS
        assert "traversal" in resp.error.message.lower()

    @pytest.mark.asyncio
    async def test_not_found(self, runtime: Runtime, tmp_path: Path) -> None:
        soul = _make_soul(runtime, tmp_path)
        server = WireServer(soul)

        soul.runtime.session.work_dir = tmp_path

        msg = JSONRPCPlanFetchMessage(
            id="1",
            params=JSONRPCPlanFetchMessage.Params(plan_file="plan/nonexistent.md"),
        )
        resp = await server._handle_plan_fetch(msg)
        assert isinstance(resp, JSONRPCErrorResponse)
        assert resp.error.code == ErrorCodes.INVALID_PARAMS


class TestHandleQuota:
    @pytest.mark.asyncio
    async def test_returns_null_when_no_data(self, runtime: Runtime, tmp_path: Path) -> None:
        from unittest.mock import patch
        from consilium.token_tracker import TokenTracker

        with patch.object(TokenTracker, "LOG_DIR", tmp_path / "token_log"):
            soul = _make_soul(runtime, tmp_path)
            server = WireServer(soul, session=runtime.session)

            msg = JSONRPCQuotaMessage(id="1")
            resp = await server._handle_quota(msg)
            assert isinstance(resp, JSONRPCSuccessResponse)
            assert resp.result is None

    @pytest.mark.asyncio
    async def test_returns_quota_from_tracker(self, runtime: Runtime, tmp_path: Path) -> None:
        from datetime import datetime, timezone
        from unittest.mock import patch
        from consilium.token_tracker import TokenLogEntry, TokenTracker

        with patch.object(TokenTracker, "LOG_DIR", tmp_path / "token_log"):
            soul = _make_soul(runtime, tmp_path)
            server = WireServer(soul, session=runtime.session)

            tracker = TokenTracker()
            tracker.log(
                TokenLogEntry(
                    timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
                    session_id=runtime.session.id,
                    turn_id="t1",
                    model="test-model",
                    tokens_in=4000,
                    tokens_out=2000,
                    active_context=200,
                )
            )

            msg = JSONRPCQuotaMessage(id="1")
            resp = await server._handle_quota(msg)
            assert isinstance(resp, JSONRPCSuccessResponse)
            assert resp.result is not None
            assert resp.result["weekly_used_minutes"] == 3  # 6000 // 2000
            assert resp.result["weekly_limit_minutes"] >= 1
            assert "weekly_remaining_minutes" in resp.result


class TestHandleTrace:
    @pytest.mark.asyncio
    async def test_trace_think_to_do(self, runtime: Runtime, tmp_path: Path) -> None:
        soul = _make_soul(runtime, tmp_path)
        server = WireServer(soul)

        think_log = PersistentLog.for_session("think-sess", "think")
        do_log = PersistentLog.for_session("do-sess", "do")

        tm = make_log_entry("message", {"role": "user", "content": "q"}, None, "think")
        think_log.append(tm)

        bo = append_bridge_out(think_log, "do-sess", [tm.id])
        bi = append_bridge_in(do_log, "think-sess", bo.id, [tm.id])

        diff = make_log_entry("diff", {"path": "a.py"}, bi.id, "do")
        do_log.append(diff)

        msg = JSONRPCTraceMessage(
            id="1",
            params=JSONRPCTraceMessage.Params(
                direction="think_to_do",
                source_session_id="think-sess",
                target_session_id="do-sess",
                entry_id=diff.id,
            ),
        )
        resp = await server._handle_trace(msg)
        assert isinstance(resp, JSONRPCSuccessResponse)
        assert len(resp.result["linked_entries"]) == 1
        assert resp.result["linked_entries"][0]["id"] == tm.id

    @pytest.mark.asyncio
    async def test_trace_do_to_think(self, runtime: Runtime, tmp_path: Path) -> None:
        soul = _make_soul(runtime, tmp_path)
        server = WireServer(soul)

        think_log = PersistentLog.for_session("think-sess", "think")
        do_log = PersistentLog.for_session("do-sess", "do")

        tm = make_log_entry("message", {"role": "user", "content": "q"}, None, "think")
        think_log.append(tm)

        bo = append_bridge_out(think_log, "do-sess", [tm.id])
        bi = append_bridge_in(do_log, "think-sess", bo.id, [tm.id])

        diff1 = make_log_entry("diff", {"path": "a.py"}, bi.id, "do")
        diff2 = make_log_entry("diff", {"path": "b.py"}, diff1.id, "do")
        do_log.append(diff1)
        do_log.append(diff2)

        msg = JSONRPCTraceMessage(
            id="1",
            params=JSONRPCTraceMessage.Params(
                direction="do_to_think",
                source_session_id="think-sess",
                target_session_id="do-sess",
                entry_id=tm.id,
            ),
        )
        resp = await server._handle_trace(msg)
        assert isinstance(resp, JSONRPCSuccessResponse)
        assert len(resp.result["linked_entries"]) == 2
        assert resp.result["linked_entries"][0]["id"] == diff1.id
        assert resp.result["linked_entries"][1]["id"] == diff2.id

    @pytest.mark.asyncio
    async def test_invalid_direction(self, runtime: Runtime, tmp_path: Path) -> None:
        soul = _make_soul(runtime, tmp_path)
        server = WireServer(soul)

        msg = JSONRPCTraceMessage(
            id="1",
            params=JSONRPCTraceMessage.Params(
                direction="invalid",
                source_session_id="s1",
                target_session_id="s2",
                entry_id="e1",
            ),
        )
        resp = await server._handle_trace(msg)
        assert isinstance(resp, JSONRPCErrorResponse)
        assert resp.error.code == ErrorCodes.INVALID_PARAMS

    @pytest.mark.asyncio
    async def test_missing_entry_returns_empty(self, runtime: Runtime, tmp_path: Path) -> None:
        soul = _make_soul(runtime, tmp_path)
        server = WireServer(soul)

        msg = JSONRPCTraceMessage(
            id="1",
            params=JSONRPCTraceMessage.Params(
                direction="think_to_do",
                source_session_id="think-sess",
                target_session_id="do-sess",
                entry_id="nonexistent",
            ),
        )
        resp = await server._handle_trace(msg)
        assert isinstance(resp, JSONRPCSuccessResponse)
        assert resp.result["linked_entries"] == []
