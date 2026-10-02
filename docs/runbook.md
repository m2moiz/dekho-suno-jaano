# Runbook: executing a milestone end to end

How a session takes one milestone from its plan issue to a release. The rules that
other issues own are linked, not repeated, so there is one copy of each to keep true.
Dated incidents are kept as incidents; nothing here describes the state of the tree
on any particular day.

## Before starting anything

**1. Find the milestone's plan issue.** Every milestone has one issue titled
`Plan: <version> end to end, <promise>`, in that milestone:

```bash
gh issue list --repo m2moiz/dekho-suno-jaano --state all --search 'in:title "Plan:"' --json number,title,milestone
```

Read it in full before touching code. It carries the order, the dependency reasoning,
what not to build yet, and an `## Issue tree` listing every child with its blockers. If
more than one issue matches a milestone, or none does, say so rather than guessing
which is authoritative. Read every issue you take, comments included: issues filed
before a refactor cite code that has moved since.

**2. Check the tree, and do not assume it is clean.**

```bash
git status --porcelain
```

If this prints anything, you have inherited someone else's uncommitted work, not made a
mistake. Read what each changed file is for (`git diff --stat`, and the open issues that
mention it) before deciding anything. Do not discard, stash or "clean up" work that is
not your claimed issue's: `git stash` hides someone's unmerged fix, not just noise. The
same rule for sessions that only run dsj is in `AGENTS.md`, "Driving dsj itself" (#135).

**3. Run the gate before writing anything, and keep its output.**

```bash
uv run just check
```

That tells you what was already broken, so a later failure can be told apart from
inherited damage. Errors in files your issue does not touch are not yours to fix; note
them and move on. If the venv needs a sync, use the full line in the README's Install
section: a `uv sync` that leaves an extra out uninstalls it (#170).

## Claiming work without collisions

`AGENTS.md` names the tracker: GitHub Issues plus a Projects v2 board, driven with
`gh-work`. `gh-work next` hides anything already assigned, which stops two sessions
landing on the same issue. It does not stop two sessions claiming two different issues
that edit the same file, and two writers in one git checkout corrupt each other's work.

So before claiming, compare the target issue's `## Where` file list against every issue
currently in progress:

```bash
gh issue list --repo m2moiz/dekho-suno-jaano --state open --json number,title,assignees \
  | jq -r '.[] | select(.assignees | length > 0) | "\(.number)\t\(.title)"'
```

If a file appears in both, the pair is not safe side by side, whatever the plan's
grouping says. Work that has to run in parallel gets one git worktree per session.

## While working

**The gate is `uv run just check`, never pytest alone** (`AGENTS.md`, "The gate", #96).
Before the final commit, also run it as CI does: Rich colours help output under
`GITHUB_ACTIONS`, and a plain-text assertion on help passed locally and failed in CI on
2026-09-23 (`37767fc`):

```bash
GITHUB_ACTIONS=true uv run just check
```

**A new test must be seen to fail without its fix.** #51's test stayed green for weeks
while checking three words that still appeared in unrelated help text after the commands
were renamed. Revert the fix, run the test, see it fail; restore it, see it pass. Both
runs observed.

**Commit only with the owner's authority.** Without it, leave the tree for review and
report the exact commands you would run. Before committing, check that `git diff` holds
only your issue's work: an approved patch once reached `main` inside another issue's
commit (#135).

**Cite code by an `rg` pattern, with the line number only as a hint** (`AGENTS.md`,
"Citing code in issues and docs", #134).

## Memory and the machine

**Cap concurrent agents at 4 on this machine.** On 2026-09-22 about 40 agents at once
exhausted the laptop's memory and Claude Code had to be force-killed.

**Run one `dsj suno` at a time.** Two at once froze the machine on 2026-09-19 (#136).
Check `memory_pressure | tail -1` before a long run.

**Never delete a transcript to force a re-run.** Write the retry to a new path and
replace the old file once the new one exists; the pattern is in the skill's
"Interrupting is cheap" and the README's whisper section (#137).

**When a worker dies mid-flight, check before assuming.** A killed process can leave a
half-written file, not just nothing. Run `git status` and `git diff`, check the file
still parses (`uv run ruff check <file>`) and the tests near it still collect
(`uv run pytest --collect-only <path>`). Keep it if it is complete; if it is a
half-write, revert only that file, and report what you found.

## Finishing a milestone

Every issue closed is necessary, not sufficient. Also confirm:

- `uv run just check` is green in a fresh run, not one left over from mid-session, and CI
  is green on the pushed commit. Both observed.
- The plan issue's own `## Done when` is satisfied line by line. A plan's done-when often
  asks for something no single issue owns.
- Anything found along the way that was out of scope is filed as its own issue, saying
  where it was found, not folded into your diff.

**Every closed milestone gets a release** (decided by the owner on 2026-09-22, recorded
on #50). The version lives in three files that `tests/test_cli_dispatch.py` holds equal,
plus the lock:

```bash
#   pyproject.toml               version = "X.Y.Z"
#   dsj/__init__.py              __version__ = "X.Y.Z"
#   .agents/skills/dsj/SKILL.md  metadata.version: X.Y.Z
uv lock
git tag vX.Y.Z
gh release create vX.Y.Z --repo m2moiz/dekho-suno-jaano --title "vX.Y.Z" --notes "..."
```

**Hand to the next milestone:** a clean tree, the plan issue closed with its done-when
checked off, new issues linked back to where they were found, and an explicit note of
any dependency that crosses into the next milestone.

## Known traps

| issue | the trap | what to do |
|---|---|---|
| #96 | `uv run pytest` alone reports green while `just check` fails on type errors | Run `uv run just check` |
| #51 | A test asserted on words that happened to appear in unrelated text | See every new test fail without its fix |
| #135 | An approved patch sat uncommitted in a shared tree and was committed inside another issue's fix | Keep the diff to what your issue's `## Where` names; file anything else |
| #170 | `uv sync --extra <one>` uninstalls every extra it does not name | Use one full sync line and add to it |
| #141 | `uv run` from a Linux sandbox on a mounted Mac checkout deletes the Mac's `.venv` | Run dsj and `just` in the Mac's own shell |
