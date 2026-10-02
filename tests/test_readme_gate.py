"""The README, held against the code it describes.

`--engine sherpa` shipped in eb6e06f and the README's flag table still offered
`parakeet|whisper` four weeks later (#48), because the only test that read the
README pinned one install line and ran in the slow lane. These are fast, so they
run in `just check` and in CI, which is where a stale table gets caught.

Each check is a pure function of the README text, so the last test can hand it a
broken copy and watch it complain. A gate nobody has seen fail is not evidence.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from dsj.asr import ENGINES

REPO = Path(__file__).resolve().parent.parent
README = REPO / "README.md"

# The flag-table row, `| `--engine parakeet\|whisper\|sherpa` | ... |`. The pipes
# are backslash-escaped because the row lives inside a markdown table.
ENGINE_ROW = re.compile(r"^\|\s*`--engine ([^`]+)`", re.MULTILINE)


def documented_engines(text: str) -> list[str]:
    """The engine names in the README's `--engine` row, in the order written."""
    rows = ENGINE_ROW.findall(text)
    assert len(rows) == 1, f"expected one `--engine` row in the README, found {len(rows)}"
    return [name.strip() for name in rows[0].replace("\\|", "|").split("|")]


def engine_problems(text: str, engines: tuple[str, ...]) -> list[str]:
    """Every disagreement between the `--engine` row and the code's ENGINES."""
    documented = documented_engines(text)
    problems = [
        f"{name} is an engine the README never names"
        for name in engines
        if name not in documented
    ]
    problems += [
        f"the README names {name}, which is not an engine"
        for name in documented
        if name not in engines
    ]
    if not problems and documented != list(engines):
        problems.append(f"the README lists {documented}, the code {list(engines)}")
    return problems


def pyproject_extras() -> list[str]:
    """Every key under `[project.optional-dependencies]`."""
    data = tomllib.loads((REPO / "pyproject.toml").read_text())
    return sorted(data["project"]["optional-dependencies"])


def undocumented_extras(text: str, extras: list[str]) -> list[str]:
    """Extras the README never shows in a form someone could install.

    `dsj[mac]`, `dsj[parakeet,whisper]` or `--extra mac` all count. A bare word
    does not: `whisper` appears all over the README as the engine's name.
    """
    return [
        extra
        for extra in extras
        if not re.search(rf"dsj\[[^\]]*\b{extra}\b[^\]]*\]|--extra {extra}\b", text)
    ]


def test_the_engine_row_names_exactly_the_engines_the_code_has() -> None:
    problems = engine_problems(README.read_text(), ENGINES)
    assert not problems, "the README's --engine row and dsj.asr.ENGINES disagree:\n  " + (
        "\n  ".join(problems)
    )


def test_every_extra_is_shown_as_something_to_install() -> None:
    missing = undocumented_extras(README.read_text(), pyproject_extras())
    assert not missing, f"pyproject defines extras the README never installs: {missing}"


def test_the_readme_checks_can_fail() -> None:
    """A guard on the guard: a fourth engine and a seventh extra must both be noticed."""
    text = README.read_text()
    assert engine_problems(text, (*ENGINES, "fake")) == [
        "fake is an engine the README never names"
    ]
    assert engine_problems(text.replace("\\|sherpa", ""), ENGINES) == [
        "sherpa is an engine the README never names"
    ]
    assert undocumented_extras(text, ["fake"]) == ["fake"]
