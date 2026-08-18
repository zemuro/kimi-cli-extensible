"""Tests for Option B: pasted-image handoff for text-only parent models."""

from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from kosong.message import Message

from consilium.soul.media_handoff import (
    _decode_data_url,
    _extract_image_parts,
    _is_text_only,
    _save_pasted_image,
    handle_pasted_images_in_turn,
)
from consilium.wire.types import ImageURLPart, TextPart

PNG_DATA = b"\x89PNG\r\n\x1a\nfakedata"
PNG_B64 = base64.b64encode(PNG_DATA).decode()
PNG_DATA_URL = f"data:image/png;base64,{PNG_B64}"


class _FakeLLM:
    def __init__(self, capabilities: set[str]) -> None:
        self.capabilities = capabilities


class _FakeSession:
    def __init__(self, work_dir: str | None = "C:\\work") -> None:
        self.work_dir = type("WD", (), {"unsafe_to_local_path": lambda self: work_dir})()


class _FakeMarket:
    def __init__(self, has_vision: bool = True) -> None:
        self._has_vision = has_vision

    def get_builtin_type(self, name: str):
        return object() if name == "vision" and self._has_vision else None


class _FakeRuntime:
    def __init__(
        self,
        capabilities: set[str] | None = None,
        work_dir: str | None = "C:\\work",
        has_vision: bool = True,
    ) -> None:
        self.llm = _FakeLLM(capabilities or {"thinking"})
        self.session = _FakeSession(work_dir)
        self.labor_market = _FakeMarket(has_vision)


# ── data URL decoding ───────────────────────────────────────────────────


def test_decode_data_url_ok():
    payload, mime, ext = _decode_data_url(PNG_DATA_URL)
    assert payload == PNG_DATA
    assert mime == "image/png"
    assert ext == ".png"


def test_decode_data_url_remote_url_returns_none():
    assert _decode_data_url("https://example.com/x.png") is None


def test_decode_data_url_invalid_base64_returns_none():
    assert _decode_data_url("data:image/png;base64,!!!notbase64!!!") is None


def test_decode_data_url_non_base64_returns_none():
    assert _decode_data_url("data:image/png,raw") is None


# ── image part extraction ───────────────────────────────────────────────


def test_extract_image_parts_finds_images():
    msg = Message(
        role="user",
        content=[TextPart(text="hi"), ImageURLPart(image_url=ImageURLPart.ImageURL(url=PNG_DATA_URL))],
    )
    parts = _extract_image_parts(msg)
    assert len(parts) == 1
    assert isinstance(parts[0], ImageURLPart)


def test_extract_image_parts_empty_when_none():
    msg = Message(role="user", content=[TextPart(text="hi")])
    assert _extract_image_parts(msg) == []


# ── temp file persistence ───────────────────────────────────────────────


def test_save_pasted_image_writes_file(tmp_path: Path):
    path = _save_pasted_image(PNG_DATA_URL, tmp_path)
    assert path is not None
    assert path.exists()
    assert path.read_bytes() == PNG_DATA
    assert path.suffix == ".png"
    assert path.parent == tmp_path / ".consilium" / "media"


def test_save_pasted_image_remote_url_returns_none(tmp_path: Path):
    assert _save_pasted_image("https://example.com/x.png", tmp_path) is None


# ── is_text_only ────────────────────────────────────────────────────────


def test_is_text_only_true_for_thinking_only():
    assert _is_text_only(_FakeRuntime({"thinking"})) is True


def test_is_text_only_false_for_image_capable():
    assert _is_text_only(_FakeRuntime({"thinking", "image_in"})) is False


def test_is_text_only_true_when_no_llm():
    rt = _FakeRuntime({"thinking"})
    rt.llm = None
    assert _is_text_only(rt) is True


# ── full handoff ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handoff_replaces_image_with_analysis(tmp_path: Path):
    runtime = _FakeRuntime({"thinking"}, str(tmp_path))
    msg = Message(
        role="user",
        content=[TextPart(text="what is this?"), ImageURLPart(image_url=ImageURLPart.ImageURL(url=PNG_DATA_URL))],
    )

    analysis_text = "The image shows a bell synth UI with sliders and a spectrogram."
    with patch(
        "consilium.soul.media_handoff._spawn_vision_for_image",
        new=AsyncMock(return_value=analysis_text),
    ) as spawn_mock:
        result = await handle_pasted_images_in_turn(msg, runtime)

    assert spawn_mock.await_count == 1
    # Image part replaced by text; original text kept.
    text_parts = [p for p in result.content if isinstance(p, TextPart)]
    assert any("Vision analysis" in p.text for p in text_parts)
    assert any("what is this?" in p.text for p in text_parts)
    assert not any(isinstance(p, ImageURLPart) for p in result.content)
    # The spawned subagent was pointed at a real temp file.
    image_path: Path = spawn_mock.await_args.args[1]  # type: ignore[attr-defined]
    assert "paste-" in image_path.name
    assert image_path.suffix == ".png"
    assert image_path.exists()


@pytest.mark.asyncio
async def test_handoff_skips_for_vision_capable_parent(tmp_path: Path):
    runtime = _FakeRuntime({"thinking", "image_in"}, str(tmp_path))
    msg = Message(
        role="user",
        content=[TextPart(text="hi"), ImageURLPart(image_url=ImageURLPart.ImageURL(url=PNG_DATA_URL))],
    )
    with patch(
        "consilium.soul.media_handoff._spawn_vision_for_image",
        new=AsyncMock(return_value="should not be called"),
    ) as spawn_mock:
        result = await handle_pasted_images_in_turn(msg, runtime)

    assert spawn_mock.await_count == 0
    assert result is msg  # untouched (vision-capable parent sees images itself)
    assert any(isinstance(p, ImageURLPart) for p in result.content)


@pytest.mark.asyncio
async def test_handoff_no_image_parts_no_spawn(tmp_path: Path):
    runtime = _FakeRuntime({"thinking"}, str(tmp_path))
    msg = Message(role="user", content=[TextPart(text="hello")])
    with patch(
        "consilium.soul.media_handoff._spawn_vision_for_image",
        new=AsyncMock(return_value="n/a"),
    ) as spawn_mock:
        result = await handle_pasted_images_in_turn(msg, runtime)
    assert spawn_mock.await_count == 0
    assert result is msg


@pytest.mark.asyncio
async def test_handoff_vision_unavailable_leaves_image(tmp_path: Path):
    runtime = _FakeRuntime({"thinking"}, str(tmp_path), has_vision=False)
    msg = Message(
        role="user",
        content=[ImageURLPart(image_url=ImageURLPart.ImageURL(url=PNG_DATA_URL))],
    )
    with patch(
        "consilium.soul.media_handoff._spawn_vision_for_image",
        new=AsyncMock(return_value=None),
    ) as spawn_mock:
        result = await handle_pasted_images_in_turn(msg, runtime)
    # No analysis produced -> no rewrite happens; message returned unchanged
    # (the original image part is preserved; the generic media strip downstream
    # will still remove it for the text-only parent, which is the fallback).
    assert spawn_mock.await_count == 1
    assert result is msg


@pytest.mark.asyncio
async def test_handoff_remote_image_url_left_untouched(tmp_path: Path):
    runtime = _FakeRuntime({"thinking"}, str(tmp_path))
    msg = Message(
        role="user",
        content=[ImageURLPart(image_url=ImageURLPart.ImageURL(url="https://example.com/x.png"))],
    )
    with patch(
        "consilium.soul.media_handoff._spawn_vision_for_image",
        new=AsyncMock(return_value="n/a"),
    ) as spawn_mock:
        result = await handle_pasted_images_in_turn(msg, runtime)
    assert spawn_mock.await_count == 0
    # Remote URLs are not saved/analyzed; the part is preserved for other paths.
    assert any(isinstance(p, ImageURLPart) for p in result.content)
