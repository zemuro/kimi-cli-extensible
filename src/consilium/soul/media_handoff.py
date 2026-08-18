"""Option B: pasted-image handoff for text-only parent models.

When a user pastes an image into the chat and the *parent* model is
text-only (no ``image_in`` capability), the image cannot be sent to the
parent. Instead of silently stripping it (which loses the information), we:

1. Write the pasted image (base64 data URL) to a temp file under the work
   dir (``.consilium/media/paste-*.png``).
2. Spawn the ``vision`` subagent with a prompt that points at that file;
   the vision subagent (qwen/qwen3.7-flash, image-capable) reads it via
   ``ReadMediaFile`` and produces a text analysis.
3. Replace the ``ImageURLPart``(s) in the user message with a text part
   containing the analysis, so the parent sees only text.

This keeps the parent fully in control (it receives the analysis and can
reason about it) while giving text-only models "eyes" for pasted images.
"""

from __future__ import annotations

import asyncio
import base64
import mimetypes
import re
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from consilium.utils.logging import logger

if TYPE_CHECKING:
    from kosong.message import ImageURLPart, Message

    from consilium.soul.agent import Runtime


# ── data URL handling ────────────────────────────────────────────────────

_DATA_URL_RE = re.compile(r"^data:(?P<mime>[^;,]+);base64,(?P<data>.+)$", re.DOTALL)

_EXT_BY_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/svg+xml": ".svg",
    "image/heic": ".heic",
    "image/heif": ".heif",
}


def _decode_data_url(data_url: str) -> tuple[bytes, str, str] | None:
    """Decode ``data:image/png;base64,...`` -> (bytes, mime, extension).

    Returns None when the URL is not a base64 data URL (e.g. an http(s) URL
    that a vision model could fetch directly — we leave those untouched).
    """
    match = _DATA_URL_RE.match(data_url.strip())
    if not match:
        return None
    mime = match.group("mime").lower()
    raw = match.group("data")
    try:
        payload = base64.b64decode(raw, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        logger.warning("Failed to decode pasted image data URL: {error}", error=exc)
        return None
    ext = _EXT_BY_MIME.get(mime) or mimetypes.guess_extension(mime) or ".img"
    return payload, mime, ext


def _extract_image_parts(message: Message) -> list[ImageURLPart]:
    """Return the ImageURLParts present in a user message."""
    from kosong.message import ImageURLPart

    return [part for part in message.content if isinstance(part, ImageURLPart)]


# ── temp file persistence ────────────────────────────────────────────────

def _media_dir(work_dir: Path | None) -> Path | None:
    """Return the media scratch dir under the work dir (creating it)."""
    if work_dir is None:
        return None
    try:
        media_dir = Path(work_dir) / ".consilium" / "media"
        media_dir.mkdir(parents=True, exist_ok=True)
        return media_dir
    except OSError as exc:
        logger.warning("Cannot create media scratch dir: {error}", error=exc)
        return None


def _save_pasted_image(data_url: str, work_dir: Path | None) -> Path | None:
    """Decode a pasted image data URL and persist it to a temp file."""
    decoded = _decode_data_url(data_url)
    if decoded is None:
        return None
    payload, mime, ext = decoded
    media_dir = _media_dir(work_dir)
    if media_dir is None:
        return None
    filename = f"paste-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}{ext}"
    path = media_dir / filename
    try:
        path.write_bytes(payload)
    except OSError as exc:
        logger.warning("Failed to write pasted image to {path}: {error}", path=path, error=exc)
        return None
    logger.info("Saved pasted image to {path} ({mime}, {size} bytes)", path=path, mime=mime, size=len(payload))
    return path


# ── vision subagent spawn ────────────────────────────────────────────────

async def _spawn_vision_for_image(runtime: Runtime, image_path: Path, user_prompt: str | None = None) -> str | None:
    """Run the vision subagent against one image, returning its text output.

    ``user_prompt`` is the accompanying text the user typed in the same
    message; if present it is forwarded to the vision model so the analysis
    is targeted at the user's actual question (not just a generic describe).
    """
    if runtime.labor_market.get_builtin_type("vision") is None:
        logger.warning("vision subagent not registered — cannot analyze pasted image")
        return None

    from consilium.subagents.runner import ForegroundRunRequest, ForegroundSubagentRunner

    prompt = (
        "A user pasted an image into the chat. The parent model is text-only "
        "and cannot see images, so you are analyzing it on its behalf.\n\n"
    )
    if user_prompt:
        prompt += (
            "The user's question about the image was:\n"
            f"> {user_prompt}\n\n"
            "Answer that question specifically. Be precise and thorough — the "
            "parent agent will act on your answer alone.\n\n"
        )
    prompt += (
        f"Read the image at: {image_path}\n"
        "Describe in detail what the image shows: any text (quote verbatim), "
        "UI elements, layout, colors, diagrams, or notable issues."
    )
    try:
        runner = ForegroundSubagentRunner(runtime)
        req = ForegroundRunRequest(
            description="Vision: analyze pasted image",
            prompt=prompt,
            requested_type="vision",
            model=None,
            resume=None,
        )
        result = await runner.run(req)
    except Exception as exc:
        logger.warning("Vision subagent failed for pasted image: {error}", error=exc)
        return None

    if result.is_error:
        logger.warning("Vision subagent returned error: {message}", message=result.message)
        return None

    if isinstance(result.output, str):
        text = result.output
    elif isinstance(result.output, list):
        text = " ".join(getattr(p, "text", "") for p in result.output)
    else:
        text = str(result.output)
    return text.strip() or None


# ── main entry ───────────────────────────────────────────────────────────

def _is_text_only(runtime: Runtime) -> bool:
    llm = getattr(runtime, "llm", None)
    if llm is None:
        return True
    caps = getattr(llm, "capabilities", None) or set()
    return "image_in" not in caps and "video_in" not in caps


async def handle_pasted_images_in_turn(
    message: Message,
    runtime: Runtime,
) -> Message:
    """Rewrite a user message so pasted images become vision-subagent analyses.

    If the parent model is text-only and the message contains image parts,
    each image is written to a temp file, analyzed by the vision subagent,
    and the ``ImageURLPart`` is replaced by a ``TextPart`` containing the
    analysis. Non-base64 image URLs (http(s)) are left untouched — a
    vision-capable subagent could fetch those, but the parent cannot see
    them either way; leaving them preserves the original data for a
    future path.

    Returns the (possibly rewritten) message.
    """
    from kosong.message import ImageURLPart, Message, TextPart

    if not _is_text_only(runtime):
        return message

    image_parts = _extract_image_parts(message)
    if not image_parts:
        return message

    # Save + analyze each pasted image (sequential; vision calls are costly).
    work_dir: Path | None = None
    try:
        work_dir = Path(str(runtime.session.work_dir.unsafe_to_local_path()))
    except Exception:
        work_dir = None

    # Gather the user's accompanying text prompt (non-image parts) so the
    # vision subagent can answer the actual question, not just describe.
    text_prompt = " ".join(
        getattr(part, "text", "").strip()
        for part in message.content
        if not isinstance(part, ImageURLPart)
    ).strip() or None

    analyses: list[str] = []
    for part in image_parts:
        data_url = part.image_url.url
        if not data_url.startswith("data:"):
            # Remote URL: parent can't see it; leave the part for other paths.
            continue
        path = _save_pasted_image(data_url, work_dir)
        if path is None:
            continue
        analysis = await _spawn_vision_for_image(runtime, path, text_prompt)
        if analysis:
            analyses.append(analysis)

    if not analyses:
        return message

    # Rebuild content: replace each data-URL image part with its analysis,
    # keep non-data-URL image parts and all other parts intact.
    new_content: list[Any] = []
    analysis_iter = iter(analyses)
    for part in message.content:
        if isinstance(part, ImageURLPart) and part.image_url.url.startswith("data:"):
            try:
                analysis = next(analysis_iter)
            except StopIteration:
                analysis = None
            if analysis:
                new_content.append(TextPart(text=f"[Vision analysis of pasted image]\n{analysis}"))
            # If analysis is None, the image is dropped (was unsupported anyway).
        else:
            new_content.append(part)

    logger.info(
        "Handed off {n} pasted image(s) to vision subagent for text-only parent",
        n=len(analyses),
    )
    return Message(role=message.role, content=new_content, tool_call_id=message.tool_call_id)
