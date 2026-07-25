from __future__ import annotations

import platform
import sys
from pathlib import Path

from inline_snapshot import snapshot


def test_pyinstaller_datas():
    from consilium.utils.pyinstaller import datas

    project_root = Path(__file__).parent.parent.parent
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    site_packages = f".venv/lib/python{python_version}/site-packages"
    rg_binary = "rg.exe" if platform.system() == "Windows" else "rg"
    has_rg_binary = (project_root / "src/consilium/deps/bin" / rg_binary).exists()
    datas = [
        (
            Path(path)
            .relative_to(project_root)
            .as_posix()
            .replace(".venv/Lib/site-packages", site_packages),
            Path(dst).as_posix(),
        )
        for path, dst in datas
    ]

    datas = [(p, d) for p, d in datas if "web/static" not in d and "vis/static" not in d]

    expected_datas = [
        (
            f"{site_packages}/dateparser/data/dateparser_tz_cache.pkl",
            "dateparser/data",
        ),
        (
            f"{site_packages}/fastmcp/../fastmcp-3.2.4.dist-info/INSTALLER",
            "fastmcp/../fastmcp-3.2.4.dist-info",
        ),
        (
            f"{site_packages}/fastmcp/../fastmcp-3.2.4.dist-info/METADATA",
            "fastmcp/../fastmcp-3.2.4.dist-info",
        ),
        (
            f"{site_packages}/fastmcp/../fastmcp-3.2.4.dist-info/RECORD",
            "fastmcp/../fastmcp-3.2.4.dist-info",
        ),
        (
            f"{site_packages}/fastmcp/../fastmcp-3.2.4.dist-info/REQUESTED",
            "fastmcp/../fastmcp-3.2.4.dist-info",
        ),
        (
            f"{site_packages}/fastmcp/../fastmcp-3.2.4.dist-info/WHEEL",
            "fastmcp/../fastmcp-3.2.4.dist-info",
        ),
        (
            f"{site_packages}/fastmcp/../fastmcp-3.2.4.dist-info/entry_points.txt",
            "fastmcp/../fastmcp-3.2.4.dist-info",
        ),
        (
            f"{site_packages}/fastmcp/../fastmcp-3.2.4.dist-info/licenses/LICENSE",
            "fastmcp/../fastmcp-3.2.4.dist-info/licenses",
        ),
        (
            "src/consilium/CHANGELOG.md",
            "consilium",
        ),
        ("src/consilium/agents/default/agent.yaml", "consilium/agents/default"),
        ("src/consilium/agents/default/coder.yaml", "consilium/agents/default"),
        ("src/consilium/agents/default/explore.yaml", "consilium/agents/default"),
        ("src/consilium/agents/default/plan.yaml", "consilium/agents/default"),
        ("src/consilium/agents/default/system.md", "consilium/agents/default"),
        ("src/consilium/agents/okabe/agent.yaml", "consilium/agents/okabe"),
        ("src/consilium/prompts/compact.md", "consilium/prompts"),
        ("src/consilium/prompts/init.md", "consilium/prompts"),
        (
            "src/consilium/skills/consilium-help/SKILL.md",
            "consilium/skills/consilium-help",
        ),
        (
            "src/consilium/skills/skill-creator/SKILL.md",
            "consilium/skills/skill-creator",
        ),
        ("src/consilium/tools/agent/description.md", "consilium/tools/agent"),
        ("src/consilium/tools/ask_user/description.md", "consilium/tools/ask_user"),
        (
            "src/consilium/tools/dmail/dmail.md",
            "consilium/tools/dmail",
        ),
        ("src/consilium/tools/background/list.md", "consilium/tools/background"),
        ("src/consilium/tools/background/output.md", "consilium/tools/background"),
        ("src/consilium/tools/background/stop.md", "consilium/tools/background"),
        (
            "src/consilium/tools/file/glob.md",
            "consilium/tools/file",
        ),
        (
            "src/consilium/tools/file/grep.md",
            "consilium/tools/file",
        ),
        (
            "src/consilium/tools/file/read.md",
            "consilium/tools/file",
        ),
        (
            "src/consilium/tools/file/read_media.md",
            "consilium/tools/file",
        ),
        (
            "src/consilium/tools/file/replace.md",
            "consilium/tools/file",
        ),
        (
            "src/consilium/tools/file/write.md",
            "consilium/tools/file",
        ),
        ("src/consilium/tools/plan/description.md", "consilium/tools/plan"),
        ("src/consilium/tools/plan/enter_description.md", "consilium/tools/plan"),
        ("src/consilium/tools/shell/bash.md", "consilium/tools/shell"),
        (
            "src/consilium/tools/think/think.md",
            "consilium/tools/think",
        ),
        (
            "src/consilium/tools/todo/set_todo_list.md",
            "consilium/tools/todo",
        ),
        (
            "src/consilium/tools/web/fetch.md",
            "consilium/tools/web",
        ),
        (
            "src/consilium/tools/web/search.md",
            "consilium/tools/web",
        ),
    ]
    if has_rg_binary:
        expected_datas.append((f"src/consilium/deps/bin/{rg_binary}", "consilium/deps/bin"))

    for item in expected_datas:
        assert item in datas, f"Missing expected data file in PyInstaller collection: {item}"


def test_pyinstaller_hiddenimports():
    from consilium.utils.pyinstaller import hiddenimports

    assert sorted(hiddenimports) == snapshot(
        [
            "consilium._build_info",
            "consilium.cli.export",
            "consilium.cli.info",
            "consilium.cli.mcp",
            "consilium.cli.plugin",
            "consilium.cli.vis",
            "consilium.cli.web",
            "consilium.tools",
            "consilium.tools.agent",
            "consilium.tools.ask_user",
            "consilium.tools.background",
            "consilium.tools.display",
            "consilium.tools.dmail",
            "consilium.tools.file",
            "consilium.tools.file.glob",
            "consilium.tools.file.grep_local",
            "consilium.tools.file.plan_mode",
            "consilium.tools.file.read",
            "consilium.tools.file.read_media",
            "consilium.tools.file.replace",
            "consilium.tools.file.utils",
            "consilium.tools.file.write",
            "consilium.tools.plan",
            "consilium.tools.plan.enter",
            "consilium.tools.plan.heroes",
            "consilium.tools.shell",
            "consilium.tools.test",
            "consilium.tools.think",
            "consilium.tools.todo",
            "consilium.tools.utils",
            "consilium.tools.web",
            "consilium.tools.web.fetch",
            "consilium.tools.web.search",
            "setproctitle",
        ]
    )


def test_pyinstaller_hiddenimports_include_lazy_cli_subcommands():
    from consilium.cli._lazy_group import LazySubcommandGroup
    from consilium.utils.pyinstaller import hiddenimports

    expected_hiddenimports = {
        module_name
        for module_name, _attribute_name, _help_text in LazySubcommandGroup.lazy_subcommands.values()
    }

    assert expected_hiddenimports <= set(hiddenimports)
