
<!-- gh-work:begin -->
## Tracking

GitHub Issues is the tracker for this repo. The board is the linked GitHub Project.

```bash
gh-work next          # ranked, unassigned, Todo only
gh-work claim 12      # take it: assignee + Status=In Progress + Start date
gh issue close 12     # finish it; the board moves it to Done
```

Claim before writing code. `next` hides assigned issues, which is what stops two
agents landing on the same one. `next` also reconciles the board first, so an issue
filed by any route is picked up before you see the list.

Priority is P0 to P2. Effort is S (one pass), M (one session), L (spans sessions).
<!-- gh-work:end -->

## Working a milestone

Follow the runbook, [docs/runbook.md](docs/runbook.md): find the plan issue, check the
tree, claim without colliding with another session, gate every change, and close with a
release.

## The gate

Before calling any change done, run `uv run just check` and paste the line it ends
with. Not `uv run pytest` alone, and not ruff alone: `just check` runs pyright on both
configs, ruff and the fast suite, and pytest skips the type checker, so a green pytest is
no evidence that `just check` passes. On 2026-09-22 two agents reported green from pytest
while type errors sat in the tree (#96).

## Citing code in issues and docs

Cite code inside a file that is actively edited, `dsj/suno.py` above all, by an `rg`
pattern that finds it, not by a line number: `rg -n 'def write_status' dsj/suno.py`.
Lines move under every change, and a stale line number still lands on real, plausible
code, so nothing tells the reader it is wrong. A line number may sit beside the pattern
as a hint. Run the pattern before writing it down, because patterns die too: the one
issues used for the token serializer stopped matching when it moved into `_token()`
(#134).

## Driving dsj itself

Read [.agents/skills/dsj/SKILL.md](.agents/skills/dsj/SKILL.md) before running `dsj`.
It carries the flag tables, the payload schema, the polling and resume semantics and the
failure modes, and `tests/test_skill_gate.py` holds it against the CLI so it cannot go
quietly stale. The README is the same tool explained to a person, and is the longer read.

dsj runs on the Mac, in the Mac's own shell. If `uname -s` does not print `Darwin`, you
are in a sandbox or VM with this checkout mounted into it: stop, and do not run `uv run`,
`uv sync` or `just` here. uv deletes a `.venv` whose interpreter link points nowhere and
rebuilds it for the platform you are on, which wipes the Mac's environment under any job
running there (#141).

Three rules for any session that runs dsj from this checkout, including one that was only
asked to transcribe something:

1. If the task turns into a change to `dsj/*.py`, even an approved one, file an issue for
   the change before running the patched tool, and put a measurement, with the command
   that produced it, behind any constant you introduce. On 2026-09-22 an approved
   167-line patch went live with neither, and was then swept into another session's
   commit (#135).
2. The checkout may not be yours alone. Run `git status` before you start and before you
   stop, and never touch a file it already shows as modified.
3. Stop only the job you started, by its pid: `$!` when you started it with `&`, or the
   `pid` its `--status` file records (#138). Never `pkill -f 'dsj suno'`, which matches
   every dsj run on the machine, another session's included.

To use it outside this checkout, symlink it once. `~/.agents/skills` is read by Codex and
by anything else that follows that convention, and `~/.claude/skills` by Claude Code:

```bash
ln -s "$PWD/.agents/skills/dsj" ~/.agents/skills/dsj
ln -s ../../.agents/skills/dsj ~/.claude/skills/dsj
```
