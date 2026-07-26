from __future__ import annotations

import asyncio
import builtins
import json
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from kaos.path import KaosPath
from kosong.message import Message

from consilium.metadata import WorkDirMeta, load_metadata, save_metadata
from consilium.session_state import SessionState, load_session_state, save_session_state
from consilium.utils.logging import logger
from consilium.utils.string import shorten
from consilium.wire.file import WireFile
from consilium.wire.types import TurnBegin


@dataclass(slots=True, kw_only=True)
class Session:
    """A session of a work directory."""

    # static metadata
    id: str
    """The session ID."""
    work_dir: KaosPath
    """The absolute path of the work directory."""
    work_dir_meta: WorkDirMeta
    """The metadata of the work directory."""
    context_file: Path
    """The absolute path to the file storing the message history."""
    wire_file: WireFile
    """The wire message log file wrapper."""

    # session state
    state: SessionState
    """Persisted session state (approval settings, plan mode, workspace scope, etc.)."""

    # refreshable metadata
    title: str
    """The title of the session."""
    updated_at: float
    """The timestamp of the last update to the session."""

    @property
    def dir(self) -> Path:
        """The absolute path of the session directory."""
        path = self.work_dir_meta.sessions_dir / self.id
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def subagents_dir(self) -> Path:
        """The absolute path of the subagent instances directory."""
        path = self.dir / "subagents"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def is_empty(self) -> bool:
        """Whether the session has any context history or a custom title."""
        if self.state.custom_title:
            return False
        if not self.wire_file.is_empty():
            return False
        
        from consilium.think.storage import think_path
        if think_path(self.id, work_dir=Path(self.work_dir_meta.path)).exists():
            return False

        try:
            with self.context_file.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    role = json.loads(line, strict=False).get("role")
                    if isinstance(role, str) and not role.startswith("_"):
                        return False
        except FileNotFoundError:
            return True
        except (OSError, ValueError, TypeError):
            logger.exception("Failed to read context file {file}:", file=self.context_file)
            return False
        return True

    def save_state(self) -> None:
        """Persist the session state to disk.

        Reloads externally-mutable fields (title, archive) from disk first
        to avoid overwriting concurrent changes made by the web API.
        """
        fresh = load_session_state(self.dir)
        self.state.custom_title = fresh.custom_title
        self.state.title_generated = fresh.title_generated
        self.state.title_generate_attempts = fresh.title_generate_attempts
        self.state.archived = fresh.archived
        self.state.archived_at = fresh.archived_at
        self.state.auto_archive_exempt = fresh.auto_archive_exempt
        save_session_state(self.state, self.dir)

    async def delete(self) -> None:
        """Delete the session directory."""
        session_dir = self.work_dir_meta.sessions_dir / self.id
        if not session_dir.exists():
            return
        await asyncio.to_thread(shutil.rmtree, session_dir, True)

    async def refresh(self) -> None:
        self.title = "Untitled"
        self.updated_at = 0.0

        if self.context_file.exists():
            self.updated_at = self.context_file.stat().st_mtime
            
        from consilium.think.storage import think_path
        think_file = think_path(self.id, work_dir=Path(self.work_dir_meta.path))
        if think_file.exists():
            think_mtime = think_file.stat().st_mtime
            if think_mtime > self.updated_at:
                self.updated_at = think_mtime
                
        if self.updated_at == 0.0:
            state_file = self.dir / "state.json"
            if state_file.exists():
                self.updated_at = state_file.stat().st_mtime
            elif self.dir.exists():
                self.updated_at = self.dir.stat().st_mtime

        if self.state.custom_title:
            self.title = self.state.custom_title
            return

        try:
            async for record in self.wire_file.iter_records():
                wire_msg = record.to_wire_message()
                if isinstance(wire_msg, TurnBegin):
                    self.title = shorten(
                        Message(role="user", content=wire_msg.user_input).extract_text(" "),
                        width=50,
                    )
                    return
        except Exception:
            logger.exception(
                "Failed to derive session title from wire file {file}:",
                file=self.wire_file.path,
            )

    @staticmethod
    async def create(
        work_dir: KaosPath,
        session_id: str | None = None,
        _context_file: Path | None = None,
    ) -> Session:
        """Create a new session for a work directory."""
        work_dir = work_dir.canonical()
        logger.debug("Creating new session for work directory: {work_dir}", work_dir=work_dir)

        metadata = load_metadata()
        work_dir_meta = metadata.get_work_dir_meta(work_dir)
        if work_dir_meta is None:
            work_dir_meta = metadata.new_work_dir_meta(work_dir)

        if session_id is None:
            session_id = str(uuid.uuid4())
        session_dir = work_dir_meta.sessions_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        if _context_file is None:
            context_file = session_dir / "context.jsonl"
        else:
            logger.warning(
                "Using provided context file: {context_file}", context_file=_context_file
            )
            _context_file.parent.mkdir(parents=True, exist_ok=True)
            if _context_file.exists():
                assert _context_file.is_file()
            context_file = _context_file

        if context_file.exists():
            # truncate if exists
            logger.warning(
                "Context file already exists, truncating: {context_file}", context_file=context_file
            )
            context_file.unlink()
        context_file.touch()

        save_metadata(metadata)

        session = Session(
            id=session_id,
            work_dir=work_dir,
            work_dir_meta=work_dir_meta,
            context_file=context_file,
            wire_file=WireFile(path=session_dir / "wire.jsonl"),
            state=SessionState(),
            title="",
            updated_at=0.0,
        )
        await session.refresh()
        return session

    @staticmethod
    async def find(work_dir: KaosPath, session_id: str) -> Session | None:
        """Find a session by work directory and session ID."""
        work_dir = work_dir.canonical()
        logger.debug(
            "Finding session for work directory: {work_dir}, session ID: {session_id}",
            work_dir=work_dir,
            session_id=session_id,
        )

        metadata = load_metadata()
        work_dir_meta = metadata.get_work_dir_meta(work_dir)
        if work_dir_meta is None:
            logger.debug("Work directory never been used")
            return None

        _migrate_session_context_file(work_dir_meta, session_id)

        session_dir = work_dir_meta.sessions_dir / session_id
        if not session_dir.is_dir():
            imported = Session._try_import_session(session_id, session_dir, work_dir_meta)
            if not imported:
                logger.debug("Session directory not found: {session_dir}", session_dir=session_dir)
                return None

        context_file = session_dir / "context.jsonl"

        session = Session(
            id=session_id,
            work_dir=work_dir,
            work_dir_meta=work_dir_meta,
            context_file=context_file,
            wire_file=WireFile(path=session_dir / "wire.jsonl"),
            state=load_session_state(session_dir),
            title="",
            updated_at=0.0,
        )
        await session.refresh()
        return session

    @staticmethod
    async def list(work_dir: KaosPath) -> builtins.list[Session]:
        """List all sessions for a work directory."""
        work_dir = work_dir.canonical()
        logger.debug("Listing sessions for work directory: {work_dir}", work_dir=work_dir)

        metadata = load_metadata()
        work_dir_meta = metadata.get_work_dir_meta(work_dir)
        if work_dir_meta is None:
            logger.debug("Work directory never been used")
            return []

        session_ids = {
            path.name if path.is_dir() else path.stem
            for path in work_dir_meta.sessions_dir.iterdir()
            if path.is_dir() or path.suffix == ".jsonl"
        }

        sessions: list[Session] = []
        for session_id in session_ids:
            _migrate_session_context_file(work_dir_meta, session_id)
            session_dir = work_dir_meta.sessions_dir / session_id
            if not session_dir.is_dir():
                logger.debug("Session directory not found: {session_dir}", session_dir=session_dir)
                continue
            context_file = session_dir / "context.jsonl"
            session = Session(
                id=session_id,
                work_dir=work_dir,
                work_dir_meta=work_dir_meta,
                context_file=context_file,
                wire_file=WireFile(path=session_dir / "wire.jsonl"),
                state=load_session_state(session_dir),
                title="",
                updated_at=0.0,
            )
            if session.is_empty():
                logger.debug(
                    "Session context file is empty: {context_file}", context_file=context_file
                )
                continue
            await session.refresh()
            sessions.append(session)
        sessions.sort(key=lambda session: session.updated_at, reverse=True)
        return sessions

    @classmethod
    async def list_all(cls) -> builtins.list[Session]:
        """List sessions across all known work directories."""
        all_sessions: list[Session] = []
        for wd in load_metadata().work_dirs:
            sessions = await cls.list(KaosPath.unsafe_from_local_path(Path(wd.path)))
            all_sessions.extend(sessions)
        
        # Deduplicate by session_id, keeping the most recently updated one
        all_sessions.sort(key=lambda s: s.updated_at, reverse=True)
        seen = set()
        deduped: list[Session] = []
        for s in all_sessions:
            if s.id not in seen:
                seen.add(s.id)
                deduped.append(s)
                
        return deduped

    @staticmethod
    async def continue_(work_dir: KaosPath) -> Session | None:
        """Get the last session for a work directory."""
        work_dir = work_dir.canonical()
        logger.debug("Continuing session for work directory: {work_dir}", work_dir=work_dir)

        metadata = load_metadata()
        work_dir_meta = metadata.get_work_dir_meta(work_dir)
        if work_dir_meta is None:
            logger.debug("Work directory never been used")
            return None
        if work_dir_meta.last_session_id is None:
            logger.debug("Work directory never had a session")
            return None

        logger.debug(
            "Found last session for work directory: {session_id}",
            session_id=work_dir_meta.last_session_id,
        )
        return await Session.find(work_dir, work_dir_meta.last_session_id)


    @classmethod
    def _try_import_session(cls, session_id: str, dest_dir: Path, work_dir_meta: WorkDirMeta | None = None) -> bool:
        """Attempt to import a session from other workspaces or think sessions."""
        import shutil
        from consilium.think.storage import think_path
        
        # Check Think sessions (workspace-local first, then global fallback)
        think_work_dir = Path(work_dir_meta.path) if work_dir_meta else None
        think_file = think_path(session_id, work_dir=think_work_dir)
        if think_file.exists():
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy(think_file, dest_dir / "wire.jsonl")
            (dest_dir / "context.jsonl").touch()
            logger.info("Imported Think session {session_id} into {dest_dir}", session_id=session_id, dest_dir=dest_dir)
            return True
            
        # Check other workspaces (legacy or just different tab)
        metadata = load_metadata()
        for wd in metadata.work_dirs:
            other_dir = wd.sessions_dir / session_id
            if other_dir.is_dir() and other_dir != dest_dir:
                dest_dir.mkdir(parents=True, exist_ok=True)
                if (other_dir / "wire.jsonl").exists():
                    shutil.copy(other_dir / "wire.jsonl", dest_dir / "wire.jsonl")
                if (other_dir / "context.jsonl").exists():
                    shutil.copy(other_dir / "context.jsonl", dest_dir / "context.jsonl")
                if (other_dir / "state.json").exists():
                    shutil.copy(other_dir / "state.json", dest_dir / "state.json")
                logger.info("Imported session {session_id} from {other_dir}", session_id=session_id, other_dir=other_dir)
                return True
                
        return False

def _migrate_session_context_file(work_dir_meta: WorkDirMeta, session_id: str) -> None:
    old_context_file = work_dir_meta.sessions_dir / f"{session_id}.jsonl"
    new_context_file = work_dir_meta.sessions_dir / session_id / "context.jsonl"
    if old_context_file.exists() and not new_context_file.exists():
        new_context_file.parent.mkdir(parents=True, exist_ok=True)
        old_context_file.rename(new_context_file)
        logger.info(
            "Migrated session context file from {old} to {new}",
            old=old_context_file,
            new=new_context_file,
        )

    # Backfill wire.jsonl for legacy sessions
    wire_file = work_dir_meta.sessions_dir / session_id / "wire.jsonl"
    if new_context_file.exists() and not wire_file.exists():
        logger.info("Backfilling wire.jsonl for legacy session {session_id}", session_id=session_id)
        with open(new_context_file, "r", encoding="utf-8") as f_in, open(wire_file, "w", encoding="utf-8") as f_out:
            for line in f_in:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    role = record.get("role")
                    if role in ("user", "assistant"):
                        event = {
                            "type": "Message",
                            "payload": {
                                "role": role,
                                "content": record.get("content", "")
                            }
                        }
                        f_out.write(json.dumps(event) + "\n")
                except json.JSONDecodeError:
                    pass
