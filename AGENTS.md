
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

## Working on the UI

`dsj ui` is a FastAPI server in `dsj/ui/` serving a React page built from `ui/`. The gate
above holds it too: `just check` also runs `tsc`, vitest, the API-types check and the
stale-build check, and `just verify` adds Playwright on chromium and webkit.

1. **Commands.**
   - `just ui-dev` to develop: the API on 127.0.0.1:8721 with reload, and Vite on 5173.
     Open the Vite URL; Ctrl-C stops both.
   - `just ui-build` before any commit that touches `ui/`, then commit what it wrote to
     `dsj/ui/static/`. Every file under `ui/` counts, tests included, because Tailwind
     reads them all for class names (#114).
   - `just api` after changing `dsj/ui/schemas.py` or a route (#155).
   - `just check` before calling anything done, not pytest and not `npm test` (#96).
   - A fresh clone needs `(cd ui && npm ci)` first: `just check` fails rather than skips
     without `ui/node_modules` (#157). `just verify` also needs the browsers, once:
     `(cd ui && npx playwright install chromium webkit)`.
2. **Where files go.** Frontend source in `ui/src/`, its tests in `ui/tests/unit/`
   (vitest) and `ui/tests/e2e/` (Playwright). The Python server in `dsj/ui/`, and the
   shape of everything it sends in `dsj/ui/schemas.py`. The built page in
   `dsj/ui/static/`, committed. The generated types in `ui/src/api/schema.d.ts`. Never
   hand-edit those last two: rebuild with `just ui-build`, regenerate with `just api`.
3. **TypeScript is pinned to 6.0.3. Do not install 7.x.** `typescript-eslint@8.70.1`
   declares `"typescript": ">=4.8.4 <6.1.0"` (checked on npm 2026-09-22, and still the
   range of 8.71.0 on 2026-10-02), and 6.0.3 is the newest version inside it. A 7.x
   installs with a warning and then lints on a compiler the linter does not support. The
   `overrides` entry in `ui/package.json` is the same pin: openapi-typescript 7.13.0
   declares `typescript ^5.x`, and the override points it at this 6.0.3 instead of
   letting npm refuse the install. Every version in `ui/package.json` is exact
   (`ui/.npmrc` has `save-exact=true`); never add a `^` or `~`.
4. **The package is `@base-ui/react`, not `@base-ui-components/react`.** It was renamed.
   The old name is frozen at `1.0.0-rc.0`, is not installed here, and importing it fails
   as `Cannot find module '@base-ui-components/react'`, which reads like a broken install
   and is not one.
5. **Never hand-write a UI primitive, and never type a `@base-ui/react/*` import from
   memory.** Run `npx shadcn@4.21.0 add <name>` from `ui/` and let it write the file and
   the import (`npx shadcn@4.21.0 add button --dry-run` shows what it would write).

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
