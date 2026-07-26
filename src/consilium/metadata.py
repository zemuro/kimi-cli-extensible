from __future__ import annotations

import json
from pathlib import Path

from kaos import get_current_kaos
from kaos.path import KaosPath
from kaos.local import local_kaos
from pydantic import BaseModel, ConfigDict, Field

from consilium.share import get_share_dir
from consilium.utils.io import atomic_json_write
from consilium.utils.path import ensure_safe_path
from consilium.utils.logging import logger


def get_metadata_file() -> Path:
    return get_share_dir() / "kimi.json"


class WorkDirMeta(BaseModel):
    """Metadata for a work directory."""

    path: str
    """The full path of the work directory."""

    kaos: str = local_kaos.name
    """The name of the KAOS where the work directory is located."""

    last_session_id: str | None = None
    """Last session ID of this work directory."""

    @property
    def sessions_dir(self) -> Path:
        """The directory to store regular (wire) sessions for this work directory.

        Returns ``{workDir}/.consilium/sessions/regular/``,
        creating it if necessary.
        """
        session_dir = Path(self.path) / ".consilium" / "sessions" / "regular"
        session_dir = ensure_safe_path(session_dir)
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir


class Metadata(BaseModel):
    """Kimi metadata structure."""

    model_config = ConfigDict(extra="ignore")

    work_dirs: list[WorkDirMeta] = Field(default_factory=list[WorkDirMeta])
    """Work directory list."""

    def get_work_dir_meta(self, path: KaosPath) -> WorkDirMeta | None:
        """Get the metadata for a work directory."""
        import sys
        target_path = str(path)
        is_win = sys.platform == "win32"
        if is_win:
            target_path = target_path.lower()

        for wd in self.work_dirs:
            if wd.kaos == get_current_kaos().name:
                wd_path = wd.path.lower() if is_win else wd.path
                if wd_path == target_path:
                    return wd
        return None

    def new_work_dir_meta(self, path: KaosPath) -> WorkDirMeta:
        """Create a new work directory metadata."""
        wd_meta = WorkDirMeta(path=str(path), kaos=get_current_kaos().name)
        self.work_dirs.append(wd_meta)
        return wd_meta


def load_metadata() -> Metadata:
    metadata_file = get_metadata_file()
    logger.debug("Loading metadata from file: {file}", file=metadata_file)
    if not metadata_file.exists():
        logger.debug("No metadata file found, creating empty metadata")
        return Metadata()
    with open(metadata_file, encoding="utf-8") as f:
        data = json.load(f)
        return Metadata(**data)


def save_metadata(metadata: Metadata):
    metadata_file = get_metadata_file()
    logger.debug("Saving metadata to file: {file}", file=metadata_file)
    atomic_json_write(metadata.model_dump(), metadata_file)
