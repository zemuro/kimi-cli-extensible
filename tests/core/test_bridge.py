"""Tests for bridge protocol and traceability."""

from __future__ import annotations

from consilium.plan.bridge import (
    append_bridge_in,
    append_bridge_out,
    find_last_bridge_in_before,
    trace_do_to_think,
    trace_think_to_do,
)
from consilium.plan.log_entry import make_log_entry
from consilium.plan.persistent_log import PersistentLog


class TestBridgeEntries:
    def test_append_bridge_out(self, tmp_path) -> None:
        think_log = PersistentLog(tmp_path / "think.jsonl", log_owner="think")
        entry = append_bridge_out(think_log, "do-sess-1", ["msg1", "msg2"])
        assert entry.type == "bridge_out"
        assert entry.payload["target_session_id"] == "do-sess-1"
        assert entry.payload["pushed_entries"] == ["msg1", "msg2"]

    def test_append_bridge_in(self, tmp_path) -> None:
        do_log = PersistentLog(tmp_path / "do.jsonl", log_owner="do")
        entry = append_bridge_in(do_log, "think-sess-1", "bridge_out_1", ["msg1"])
        assert entry.type == "bridge_in"
        assert entry.payload["source_session_id"] == "think-sess-1"
        assert entry.payload["source_entry"] == "bridge_out_1"


class TestTraceability:
    def test_trace_think_to_do(self, tmp_path) -> None:
        think_log = PersistentLog(tmp_path / "think.jsonl", log_owner="think")
        do_log = PersistentLog(tmp_path / "do.jsonl", log_owner="do")

        # Think messages
        tm1 = make_log_entry("message", {"role": "user", "content": "q"}, None, "think")
        tm2 = make_log_entry("message", {"role": "assistant", "content": "a"}, tm1.id, "think")
        think_log.append(tm1)
        think_log.append(tm2)

        # Bridge out
        bo = append_bridge_out(think_log, "do-sess", [tm1.id, tm2.id])

        # Bridge in
        bi = append_bridge_in(do_log, "think-sess", bo.id, [tm1.id, tm2.id])

        # Do diff
        diff = make_log_entry("diff", {"path": "foo.py"}, bi.id, "do")
        do_log.append(diff)

        result = trace_think_to_do(diff, do_log, think_log)
        assert len(result) == 2
        assert result[0].id == tm1.id
        assert result[1].id == tm2.id

    def test_trace_think_to_do_no_bridge(self, tmp_path) -> None:
        think_log = PersistentLog(tmp_path / "think.jsonl", log_owner="think")
        do_log = PersistentLog(tmp_path / "do.jsonl", log_owner="do")

        diff = make_log_entry("diff", {"path": "foo.py"}, None, "do")
        do_log.append(diff)

        result = trace_think_to_do(diff, do_log, think_log)
        assert result == []

    def test_find_last_bridge_in_before(self, tmp_path) -> None:
        do_log = PersistentLog(tmp_path / "do.jsonl", log_owner="do")

        bi1 = append_bridge_in(do_log, "sess1", "bo1", [])
        diff = make_log_entry("diff", {"path": "a.py"}, bi1.id, "do")
        do_log.append(diff)
        append_bridge_in(do_log, "sess2", "bo2", [])

        found = find_last_bridge_in_before(do_log, diff.id)
        assert found is not None
        assert found.id == bi1.id

    def test_trace_do_to_think(self, tmp_path) -> None:
        think_log = PersistentLog(tmp_path / "think.jsonl", log_owner="think")
        do_log = PersistentLog(tmp_path / "do.jsonl", log_owner="do")

        tm = make_log_entry("message", {"role": "user", "content": "q"}, None, "think")
        think_log.append(tm)

        bo = append_bridge_out(think_log, "do-sess", [tm.id])
        bi = append_bridge_in(do_log, "think-sess", bo.id, [tm.id])

        diff1 = make_log_entry("diff", {"path": "a.py"}, bi.id, "do")
        diff2 = make_log_entry("diff", {"path": "b.py"}, diff1.id, "do")
        do_log.append(diff1)
        do_log.append(diff2)

        result = trace_do_to_think(tm, think_log, do_log)
        assert len(result) == 2
        assert result[0].id == diff1.id
        assert result[1].id == diff2.id

    def test_trace_do_to_think_no_bridge(self, tmp_path) -> None:
        think_log = PersistentLog(tmp_path / "think.jsonl", log_owner="think")
        do_log = PersistentLog(tmp_path / "do.jsonl", log_owner="do")

        tm = make_log_entry("message", {"role": "user", "content": "q"}, None, "think")
        think_log.append(tm)

        result = trace_do_to_think(tm, think_log, do_log)
        assert result == []
