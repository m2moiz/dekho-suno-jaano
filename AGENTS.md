
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

To use it outside this checkout, symlink it once. `~/.agents/skills` is read by Codex and
by anything else that follows that convention, and `~/.claude/skills` by Claude Code:

```bash
ln -s "$PWD/.agents/skills/dsj" ~/.agents/skills/dsj
ln -s ../../.agents/skills/dsj ~/.claude/skills/dsj
```
