"""The agent skill, executed and compared rather than described.

`.agents/skills/dsj/` tells an agent which flags exist, what the payload looks like and
what a run does when it is interrupted. Every one of those is a claim about code that
moves, and the agent reading it has no way to notice when it stops being true: a renamed
flag arrives as a usage error with nothing pointing at the document that caused it.

README.md is the worked example. `--engine sherpa` shipped in eb6e06f and the README's
flag table still said `parakeet|whisper` afterwards, because nothing compared the two.

So this file compares them. The fast tests hold the skill against the live Typer app and
against the package source, and they run in `just check` and therefore in CI, which is
where flag drift actually gets caught.

The slow test runs the skill's own documented command sequence. It synthesises its media
with ffmpeg rather than reading the gitignored clips in scratch/, so it needs no fixture
and nothing has to be committed for it. That does NOT make it a CI test: it still loads
2.4 GB of parakeet weights, which is the reason ci.yml keeps the whole slow lane out. Its
observer is `just verify` at session close, like every other slow gate here.

There is also a test that breaks a copy of the skill on purpose and asserts the checker
notices, because a gate nobody has seen fail is not evidence (docs/tooling-gaps.md, 14).
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, cast

import pytest
from click import Group
from typer.main import get_command

import dsj.cli

REPO = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO / ".agents" / "skills" / "dsj"
SKILL = SKILL_DIR / "SKILL.md"

# The three verbs each get a level-3 section in SKILL.md whose body carries the flag
# table this gate reads. The heading text is load-bearing, not decoration.
VERB_HEADING = re.compile(r"^###\s+(\w+)\s*$", re.MULTILINE)

# Long or short, as they appear inside backticks in a table cell or on a command line.
OPTION = re.compile(r"(?<![\w-])(--?[A-Za-z][A-Za-z0-9-]*)")

# `dsj suno ...`, with or without a `uv run` prefix, found anywhere on the line so that
# `open "$(dsj dikhao ...)"` is read too.
INVOCATION = re.compile(r"\bdsj\s+(suno|dekho|dikhao|likho|parho)\b(?P<rest>.*)")

FENCE = re.compile(r"^```(\w*)\n(.*?)^```", re.MULTILINE | re.DOTALL)

# The single-quoted program out of a `jq -r '...' file.json` line in the skill. Flags are
# skipped loosely rather than enumerated: a pattern that only understood the flags in use
# today would stop matching a recipe that grew one, and stop matching in silence.
JQ_PROGRAM = re.compile(r"\bjq\s+[^'\n]*'([^']+)'")
JQ_CALL = re.compile(r"\bjq\s")

CONSOLE_SCRIPT = Path(sys.executable).parent / "dsj"


# --------------------------------------------------------------------------
# What the code actually offers
# --------------------------------------------------------------------------


def cli_options() -> dict[str, set[str]]:
    """Every option string the CLI accepts, per verb, straight off the Typer app.

    Read from the constructed Click group rather than from `--help` text: Rich wraps
    that output at the terminal width, so parsing it would make this gate depend on how
    wide the window happened to be.
    """
    group = cast(Group, get_command(dsj.cli.app))
    return {
        name: {opt for param in command.params for opt in param.opts if opt.startswith("-")}
        for name, command in group.commands.items()
    }


def top_level_options() -> set[str]:
    """The options `dsj` itself takes, before any verb, other than --help.

    cli_options() reads only the verbs, so until #50 added a callback to the app
    there was nothing here to read, and a top-level flag could ship undocumented
    with this whole file green.
    """
    group = cast(Group, get_command(dsj.cli.app))
    return {
        opt for param in group.params for opt in param.opts if opt.startswith("-")
    } - {"--help"}


def source_states() -> set[str]:
    """The `state` values the code can write into a `--status` file.

    Two shapes produce one: `report(progress, "running")` in suno.py, and the literal
    `{"state": "failed", ...}` the CLI writes when a run raises.
    """
    states: set[str] = set()
    for path in (REPO / "dsj" / "suno.py", REPO / "dsj" / "cli.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "report"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)
            ):
                states.add(node.args[1].value)
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values, strict=True):
                    if (
                        isinstance(key, ast.Constant)
                        and key.value == "state"
                        and isinstance(value, ast.Constant)
                        and isinstance(value.value, str)
                    ):
                        states.add(value.value)
    return states


def package_source() -> str:
    """Every line of the package, for checking that a documented name exists at all."""
    return "\n".join(path.read_text() for path in sorted((REPO / "dsj").glob("*.py")))


# --------------------------------------------------------------------------
# What the skill claims
# --------------------------------------------------------------------------


def skill_documents() -> list[Path]:
    """SKILL.md and every reference beside it."""
    return [SKILL, *sorted((SKILL_DIR / "references").glob("*.md"))]


def sections(text: str) -> dict[str, str]:
    """Split SKILL.md into its level-3 verb sections, keyed by heading word."""
    found = list(VERB_HEADING.finditer(text))
    out: dict[str, str] = {}
    for i, match in enumerate(found):
        end = found[i + 1].start() if i + 1 < len(found) else len(text)
        body = text[match.end() : end]
        # A level-2 heading ends the section too, so later prose cannot drag itself
        # into a verb's table.
        stop = re.search(r"^##\s", body, re.MULTILINE)
        out[match.group(1)] = body[: stop.start()] if stop else body
    return out


def table_options(text: str, verb: str) -> set[str]:
    """The options in one verb's flag table, read from the first cell of every row."""
    section = sections(text).get(verb, "")
    options: set[str] = set()
    for line in section.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = line.split("|")
        if len(cells) < 2:
            continue
        options.update(OPTION.findall(cells[1]))
    return options


def flag_table_problems(text: str, actual: dict[str, set[str]]) -> list[str]:
    """Every disagreement between the skill's flag tables and the CLI, as sentences.

    A pure function of the text, so that `test_the_flag_check_can_fail` can hand it a
    deliberately broken copy and watch it complain.
    """
    problems: list[str] = []
    for verb, real in sorted(actual.items()):
        documented = table_options(text, verb)
        if not documented:
            problems.append(f"{verb}: SKILL.md has no `### {verb}` section with a flag table")
            continue
        problems += [
            f"{verb}: {missing} exists in the CLI and the skill never names it"
            for missing in sorted(real - documented)
        ]
        problems += [
            f"{verb}: the skill documents {invented}, which the CLI does not have"
            for invented in sorted(documented - real)
        ]
    return problems


def example_commands(text: str) -> list[tuple[str, str, str]]:
    """Every `dsj <verb> ...` line in a fenced block, as (verb, option, whole line)."""
    found: list[tuple[str, str, str]] = []
    for language, body in FENCE.findall(text):
        if language not in ("bash", "sh", ""):
            continue
        for line in body.splitlines():
            match = INVOCATION.search(line)
            if match is None:
                continue
            found += [
                (match.group(1), option, line.strip())
                for option in OPTION.findall(match.group("rest"))
            ]
    return found


def json_examples(text: str) -> list[Any]:
    """Every fenced json block, parsed. A malformed block raises here, which is the point."""
    return [json.loads(body) for language, body in FENCE.findall(text) if language == "json"]


def jq_programs() -> list[str]:
    """Every jq program the skill hands a reader, across SKILL.md and the references.

    Raises:
        AssertionError: if a `jq` line exists that the pattern could not read. A recipe
            the extractor skips is a recipe nothing checks, which is the failure this
            whole file is about.
    """
    programs: list[str] = []
    for document in skill_documents():
        # Fenced blocks only. The word "jq" also appears in prose, and counting those
        # as recipes is how the first version of this check failed.
        for language, body in FENCE.findall(document.read_text()):
            if language not in ("bash", "sh", ""):
                continue
            found = JQ_PROGRAM.findall(body)
            assert len(found) == len(JQ_CALL.findall(body)), (
                f"{document.name} has a jq recipe this test cannot extract, so nothing "
                f"would run it: {len(JQ_CALL.findall(body))} calls, {len(found)} readable"
            )
            programs += found
    return programs


# --------------------------------------------------------------------------
# The fast gate
# --------------------------------------------------------------------------


def test_the_skill_is_where_the_install_instructions_point() -> None:
    assert SKILL.is_file(), f"no SKILL.md at {SKILL}"
    assert (SKILL_DIR / "references").is_dir()
    head = SKILL.read_text()[:400]
    assert head.startswith("---"), "SKILL.md must open with YAML frontmatter"
    assert "name: dsj" in head
    assert "description:" in head


def test_the_skill_documents_exactly_the_verbs_that_exist() -> None:
    documented = set(sections(SKILL.read_text()))
    actual = set(cli_options())
    assert documented == actual, f"skill documents {sorted(documented)}, CLI has {sorted(actual)}"


def test_each_verb_table_lists_exactly_the_flags_the_cli_has() -> None:
    problems = flag_table_problems(SKILL.read_text(), cli_options())
    assert not problems, "the skill and the CLI disagree:\n  " + "\n  ".join(problems)


def test_every_top_level_option_is_in_the_first_command_block() -> None:
    """`dsj --version` belongs where an agent looks before its first command."""
    text = SKILL.read_text()
    start = text.index("## Before the first command")
    first = text[start : text.index("\n## ", start + 1)]
    commands = "\n".join(body for _, body in FENCE.findall(first))
    options = top_level_options()
    assert options, "the app has no top-level options; the #50 callback is gone"
    missing = sorted(o for o in options if f"dsj {o}" not in commands)
    assert not missing, f"top-level options the skill never shows an agent: {missing}"


def test_no_example_command_uses_a_flag_its_verb_does_not_have() -> None:
    actual = cli_options()
    wrong = [
        f"{line!r} passes {option} to {verb}, which takes {sorted(actual[verb])}"
        for document in skill_documents()
        for verb, option, line in example_commands(document.read_text())
        if option not in actual[verb]
    ]
    assert not wrong, "example commands that would not run:\n  " + "\n  ".join(wrong)


def test_every_json_example_parses_and_names_only_real_keys() -> None:
    source = package_source()
    unknown: list[str] = []
    for document in skill_documents():
        for parsed in json_examples(document.read_text()):
            if not isinstance(parsed, dict):
                continue
            keys = cast("dict[str, Any]", parsed).keys()
            unknown += [
                f"{document.name}: {key!r} appears in no dsj module"
                for key in keys
                if key not in source
            ]
    assert not unknown, "keys the skill invents:\n  " + "\n  ".join(unknown)


def test_every_status_state_the_code_can_write_is_documented() -> None:
    text = "\n".join(document.read_text() for document in skill_documents())
    missing = [state for state in sorted(source_states()) if f"`{state}`" not in text]
    assert not missing, f"the code writes these states and the skill never names them: {missing}"


def test_the_flag_check_can_fail() -> None:
    """A guard on the guard.

    Rename one flag in a copy of the skill and the checker must say so. Without this the
    tests above could be passing because they compare nothing.
    """
    actual = cli_options()
    original = SKILL.read_text()
    assert not flag_table_problems(original, actual), "precondition: the real skill is clean"

    broken = original.replace("--no-resume", "--no-resumeXX")
    assert broken != original, "expected --no-resume to be documented"
    problems = flag_table_problems(broken, actual)
    assert any("--no-resume exists in the CLI" in problem for problem in problems), problems


# --------------------------------------------------------------------------
# The slow gate: the documented workflow, run
# --------------------------------------------------------------------------


def synthesise(work: Path) -> tuple[Path, Path]:
    """Four minutes of tone, and an 18-second video with exactly two cuts.

    Synthesised rather than committed so the gate runs anywhere ffmpeg does. Four
    minutes because the chunk stride is 105 seconds and the resume half of this test
    needs more than one chunk; three flat colours because the mark pass must then find
    exactly two boundaries and nothing else.
    """
    tone = work / "tone.wav"
    cuts = work / "cuts.mp4"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000:duration=240",
         "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(tone)],
        check=True, capture_output=True, timeout=120,
    )
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "color=c=black:s=640x400:d=6",
         "-f", "lavfi", "-i", "color=c=white:s=640x400:d=6",
         "-f", "lavfi", "-i", "color=c=red:s=640x400:d=6",
         "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
         "-map", "[v]", "-r", "10", "-pix_fmt", "yuv420p", str(cuts)],
        check=True, capture_output=True, timeout=120,
    )
    return tone, cuts


@pytest.mark.slow
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")
@pytest.mark.skipif(not CONSOLE_SCRIPT.is_file(), reason="no dsj console script in this env")
def test_the_documented_workflow_runs(tmp_path: Path) -> None:
    """One heartbeat-watched run, an interrupt, a resume, then dekho and dikhao.

    The skill's acceptance criterion turned into a command sequence: the four things a
    fresh agent is told it can do.
    """
    tone, cuts = synthesise(tmp_path)
    out = tmp_path / "transcript.json"
    status = tmp_path / "run.json"
    ckpt = out.with_name(out.name + ".ckpt")
    command = [str(CONSOLE_SCRIPT), "suno", str(tone), "-o", str(out),
               "--status", str(status), "--no-diarize"]

    # 1. Interrupt once a checkpoint exists. Waiting on the file rather than on a clock
    #    is what keeps this from being a race.
    first = subprocess.Popen(command, stderr=subprocess.PIPE, text=True)
    deadline = time.monotonic() + 300
    while not ckpt.exists():
        assert first.poll() is None, "the run finished before it wrote a checkpoint"
        assert time.monotonic() < deadline, "no checkpoint within 300s"
        time.sleep(0.05)
    banked = json.loads(ckpt.read_text())
    assert set(banked) == {"media", "fingerprint", "next_start", "tokens"}
    assert banked["next_start"] > 0

    first.send_signal(signal.SIGINT)
    assert first.wait(timeout=120) == 130, "Ctrl-C should exit 130"
    assert ckpt.exists(), "the checkpoint must survive an interrupt"
    assert not out.exists(), "an interrupted run must not write a transcript"

    # 2. The same command resumes rather than starting over.
    second = subprocess.run(command, capture_output=True, text=True, timeout=900)
    assert second.returncode == 0, second.stderr
    assert "resuming from" in second.stderr, second.stderr
    assert not ckpt.exists(), "the checkpoint must be removed once the transcript lands"
    assert not second.stdout, "suno writes nothing to stdout"

    payload = json.loads(out.read_text())
    assert set(payload) == {"audio", "model", "text", "sentences"}
    assert payload["audio"] == str(tone)

    # 3. The heartbeat ends in a terminal state. `state`, never `fraction`: fraction
    #    reaches 1.0 before labelling starts and drops to 0.0 for the diarizing frames.
    #    The done frame reports the length of the audio (#52), so the tone, which has
    #    no speech in it, still ends at its full 240 s rather than at 0.0.
    heartbeat = json.loads(status.read_text())
    assert heartbeat["state"] == "done", heartbeat
    assert set(heartbeat) >= {"state", "fraction", "speed", "eta_s", "audio_done_s"}
    assert heartbeat["audio_total_s"] == pytest.approx(240.0)

    # 4. dekho merges marks into the transcript it is given.
    marked = tmp_path / "marked.json"
    dekho = subprocess.run(
        [str(CONSOLE_SCRIPT), "dekho", str(cuts), "-t", str(out), "-o", str(marked)],
        capture_output=True, text=True, timeout=300,
    )
    assert dekho.returncode == 0, dekho.stderr
    document = json.loads(marked.read_text())
    assert set(document) == {"audio", "model", "text", "sentences", "marks", "marks_meta"}
    assert len(document["marks"]) == 2, document["marks"]
    for mark in document["marks"]:
        assert set(mark) == {"t", "score", "look"}
        assert mark["look"] >= mark["t"]

    # 5. dikhao takes `look`, prints the path on stdout, and writes an image.
    frame = tmp_path / "frame.jpg"
    dikhao = subprocess.run(
        [str(CONSOLE_SCRIPT), "dikhao", str(cuts), str(document["marks"][0]["look"]),
         "-o", str(frame)],
        capture_output=True, text=True, timeout=300,
    )
    assert dikhao.returncode == 0, dikhao.stderr
    assert dikhao.stdout.strip() == str(frame), dikhao.stdout
    assert frame.stat().st_size > 0

    # 6. Every jq program the skill hands a reader runs against the documents this run
    #    just produced. A recipe with a typo in a field name is the same class of defect
    #    as a wrong flag, and reads exactly as authoritative.
    if shutil.which("jq") is None:
        pytest.skip("jq not on PATH, so the recipes cannot be executed")
    programs = jq_programs()
    assert programs, "the skill should carry query recipes"
    for program in programs:
        results = [
            subprocess.run(["jq", "-r", program, str(document)],
                           capture_output=True, text=True, timeout=60)
            for document in (marked, status)
        ]
        assert any(result.returncode == 0 for result in results), (
            f"jq recipe runs against neither the transcript nor the heartbeat:"
            f"\n  {program}\n  {results[0].stderr.strip()}"
        )

    # 7. A recipe that reads `state` is a recipe someone will point at a run that
    #    failed, and the failure document carries only two keys. The first version of
    #    the polling recipe here died on it with "null and number cannot be
    #    multiplied", which is the shape of bug this whole file exists to catch.
    failed = tmp_path / "failed.json"
    failed.write_text(json.dumps({"state": "failed", "error": "FileNotFoundError: /nope"}))
    for program in programs:
        if ".state" not in program:
            continue
        result = subprocess.run(["jq", "-r", program, str(failed)],
                                capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, (
            f"a recipe that reads .state dies on the failure document:"
            f"\n  {program}\n  {result.stderr.strip()}"
        )
