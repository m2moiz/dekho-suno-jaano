"""AGENTS.md's "Working on the UI" and the skill's copy of it name real things (#115).

The section exists so an agent does not guess a pin or a command from training
data. A rule that names a recipe since renamed, or a pin since moved, is the
same wrong guess with the repo's authority behind it.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DOCS = [REPO / "AGENTS.md", REPO / ".agents" / "skills" / "dsj" / "SKILL.md"]
PACKAGE = json.loads((REPO / "ui" / "package.json").read_text())


def ui_section(doc: Path) -> str:
    text = doc.read_text()
    start = text.index("Working on the UI")
    end = text.find("\n## ", start)
    return text[start:] if end == -1 else text[start:end]


def recipes() -> set[str]:
    done = subprocess.run(
        ["just", "--summary"], cwd=REPO, capture_output=True, text=True, check=True, timeout=30
    )
    return set(done.stdout.split())


@pytest.mark.parametrize("doc", DOCS, ids=lambda doc: doc.name)
def test_every_just_recipe_the_ui_rules_name_exists(doc: Path) -> None:
    named = set(re.findall(r"`just ([a-z][a-z-]*)", ui_section(doc)))
    assert {"ui-dev", "ui-build", "api", "check"} <= named
    assert named <= recipes(), sorted(named - recipes())


@pytest.mark.parametrize("doc", DOCS, ids=lambda doc: doc.name)
def test_the_pins_the_ui_rules_state_are_the_pins_in_package_json(doc: Path) -> None:
    section = ui_section(doc)
    deps = PACKAGE["dependencies"] | PACKAGE["devDependencies"]
    assert f"pinned to {deps['typescript']}" in section
    assert f"npx shadcn@{deps['shadcn']} add" in section
    assert "@base-ui/react" in deps
    assert "`@base-ui/react`, not `@base-ui-components/react`" in section
