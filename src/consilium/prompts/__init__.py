from __future__ import annotations

from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent

INIT = (_PROMPTS_DIR / "init.md").read_text(encoding="utf-8")
COMPACT = (_PROMPTS_DIR / "compact.md").read_text(encoding="utf-8")

COMPACTION_SYSTEM = (_PROMPTS_DIR / "compaction_system.md").read_text(encoding="utf-8")
COMPACTION_OUTPUT = (_PROMPTS_DIR / "compaction_output.md").read_text(encoding="utf-8")

SIDE_QUESTION = (_PROMPTS_DIR / "side_question.md").read_text(encoding="utf-8")

PLAN_MODE_FULL = (_PROMPTS_DIR / "plan_mode_full.md").read_text(encoding="utf-8")
PLAN_MODE_SPARSE = (_PROMPTS_DIR / "plan_mode_sparse.md").read_text(encoding="utf-8")
PLAN_MODE_REENTRY = (_PROMPTS_DIR / "plan_mode_reentry.md").read_text(encoding="utf-8")

AFK_MODE = (_PROMPTS_DIR / "afk_mode.md").read_text(encoding="utf-8")
AFK_DISABLED = (_PROMPTS_DIR / "afk_disabled.md").read_text(encoding="utf-8")

INIT_COMPLETE = (_PROMPTS_DIR / "init_complete.md").read_text(encoding="utf-8")
ADD_DIR = (_PROMPTS_DIR / "add_dir.md").read_text(encoding="utf-8")
