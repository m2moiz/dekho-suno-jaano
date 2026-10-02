# The fast inner loop. Same thing plain `uv run pytest` gives you -- the
# deselection lives in pyproject addopts, not here, so the two cannot drift.
test:
    uv run pytest

# Two pyright invocations, not one: pyproject holds exactly one [tool.pyright]
# table, and the package and the tests need separate configs. Per-directory
# typeCheckingMode via executionEnvironments was measured and does not work --
# the total went UP rather than splitting.
typecheck:
    uv run pyright --project pyrightconfig.json
    uv run pyright --project pyrightconfig.tests.json

# THE GATE. Lint, types and the fast suite, in the order that fails cheapest
# first. One command for a human, for a coding agent, and for CI -- so a green
# here means the same thing to all three, and local and CI cannot drift.
#
# NOT pre-commit. `pre-commit install` refuses outright in this repo:
# core.hooksPath is set to .beads/hooks by `bd init`, and globally to
# ~/.githooks. Its own remedy -- `git config --unset-all core.hooksPath` --
# would disable the beads hooks AND every global hook on this machine, a blast
# radius outside this project. Worse, a pre-commit config would have LOOKED
# installed: the beads hook still runs and still exits 0, so the phase would
# have been recorded as landed while doing nothing. That is exactly the
# covered-but-unasserted failure this whole effort exists to remove.
#
# No formatter, deliberately. This codebase has a hand-set style -- aligned
# argv lists, comment-dense blocks -- and running one is a whole-tree diff
# nobody asked for.
#
# The frontend is held by the same command (#157): the committed build against
# its sources (#114), tsc over ui/, the API types against the Python models
# (#155), and vitest. None of them skips when ui/node_modules is missing.
# Browsers are not here; they are in `verify`.
check: ui-fresh typecheck ui-typecheck api-fresh
    uv run ruff check .
    {{ quote(just_executable()) }} ui-test
    uv run pytest

# Everything, with coverage. The session-close gate, and the named observer
# that makes deselecting the slow tests honest rather than a quiet loss.
# `-m "slow or not slow"` rather than `-m ""`: it unambiguously overrides the
# deselection in addopts, and empty-marker behaviour is not worth relying on.
#
# --cov-fail-under is not a quality bar, it is a LIVENESS check. This line said
# `--cov=deixis` for as long as the package has been called dsj: coverage
# collected nothing, printed "Module deixis was never imported" and "No data
# was collected" into the middle of a 22-minute run, and exited 0. Every
# coverage number quoted after the rename measured a package that did not
# exist. A floor turns that silence into a failure -- no data reads as 0%.
#
# Then everything `check` runs on the frontend, and the browser tests in real
# chromium and Playwright's webkit (ui/playwright.config.ts says what they do
# not cover).
verify: ui-fresh typecheck ui-typecheck api-fresh urdu-fixture
    uv run ruff check .
    {{ quote(just_executable()) }} ui-test
    uv run pytest -m "slow or not slow" --cov=dsj --cov-report=term-missing:skip-covered --cov-fail-under=90
    {{ quote(just_executable()) }} ui-e2e

# The public Urdu-English test recording (#148): 12.5 minutes of one
# code-switching speaker from UrduSpeech (CC-BY-4.0), stitched, with three quiet
# gaps and a ground-truth transcript, into scratch/urdu_cs/. Downloads about
# 64 MB once, then rebuilds from that cache and checks the pinned sha256.
# verify depends on it because the tests that read it FAIL when it is missing
# rather than skip: a fixture test that skips on a fresh clone is green without
# having run.
urdu-fixture:
    uv run python scratch/build_urdu_fixture.py

# Mutation testing over the three pure modules. Coverage proves a line ran;
# this proves the suite would notice if it stopped. Survivors are the
# deliverable -- triage them against docs/mutmut-triage.md, which records why
# each accepted one cannot be killed. Chasing 100% is how this becomes busywork.
#
# mutmut caches by source hash and does NOT notice new TESTS, so a rerun after
# writing a killing test needs the mutants/ tree removed first.
mutate:
    rm -rf mutants
    uv run mutmut run
    uv run mutmut results

# The page `dsj ui` serves, built from ui/ into dsj/ui/static/. The output is
# committed, so `uv tool install` ships it and needs no Node (#57 section 8).
# `npm ci`, not `npm install`: the lockfile decides what is built, and a build
# that quietly re-resolved a dependency would commit code nobody chose.
# The manifest is written AFTER the build, because Vite's emptyOutDir wipes
# dsj/ui/static/ first; `ui-fresh` (in `check`) reads it (#114).
ui-build:
    cd ui && npm ci && npm run build
    uv run python scratch/ui_manifest.py write

# Fails, naming `just ui-build`, when anything under ui/ changed since the
# committed page was built. Hashes files and needs no Node, so it has nothing
# to skip on: it runs, and fails, without ui/node_modules too.
ui-fresh:
    uv run python scratch/ui_manifest.py check

# The API with --reload on 127.0.0.1:8721, and Vite's dev server on 5173
# passing /api and /media through to it (ui/vite.config.ts). Open the Vite URL.
# Ctrl-C stops both: the trap takes the API down with the page.
ui-dev:
    #!/usr/bin/env bash
    set -euo pipefail
    uv run uvicorn dsj.ui.server:dev_app --factory --reload --reload-dir dsj --host 127.0.0.1 --port 8721 &
    api=$!
    trap 'kill "$api" 2>/dev/null' EXIT
    cd ui && npm run dev

# The frontend's API types (#155). FastAPI writes the app's OpenAPI description
# from dsj/ui/schemas.py and the routes, and openapi-typescript turns it into
# ui/src/api/schema.d.ts, which ui/src/api/client.ts is typed from. Run it after
# changing a model or a route; `check` fails until you do.
api: (_api-types "ui/src/api/schema.d.ts")

# The drift check inside `check`: regenerate into a temp file and compare with
# the one in the tree. Not `git diff --exit-code`, which would pass a stale file
# that is merely uncommitted and fail a fresh one that is.
api-fresh:
    #!/usr/bin/env bash
    set -euo pipefail
    fresh=$(mktemp)
    trap 'rm -f "$fresh"' EXIT
    {{ quote(just_executable()) }} _api-types "$fresh"
    if ! cmp -s "$fresh" ui/src/api/schema.d.ts; then
        # diff exits 1 whenever the files differ, which here is the expected case.
        { diff -u ui/src/api/schema.d.ts "$fresh" || :; } | head -40 >&2
        echo "stale API types: ui/src/api/schema.d.ts does not match dsj/ui/schemas.py -- run: just api" >&2
        exit 1
    fi

# Written to a temp file and moved into place, so a generator that dies halfway
# leaves the old file rather than half a new one. dev_app() rather than
# create_app(): it is the stable entry `just ui-dev` already depends on.
_api-types out: _ui-modules
    #!/usr/bin/env bash
    set -euo pipefail
    spec=$(mktemp)
    types=$(mktemp)
    trap 'rm -f "$spec" "$types"' EXIT
    uv run python -c 'import json; from dsj.ui.server import dev_app; print(json.dumps(dev_app().openapi()))' > "$spec"
    {
        echo '// GENERATED by `just api` from dsj/ui/schemas.py. DO NOT EDIT: change the Python models, then run `just api`.'
        ui/node_modules/.bin/openapi-typescript "$spec"
    } > "$types"
    chmod 644 "$types"
    mv "$types" {{ quote(out) }}

# The frontend's types: ui/src, its tests and its configs, under the pinned
# TypeScript 6.0.3 (#115). A type error anywhere in ui/ fails `check`.
ui-typecheck: _ui-modules
    cd ui && ./node_modules/.bin/tsc --noEmit

# Vitest with React Testing Library, ui/tests/unit only (ui/vitest.config.ts).
# Vitest exits non-zero when it finds no test files, so emptying the directory
# fails too.
ui-test: _ui-modules
    cd ui && ./node_modules/.bin/vitest run

# Playwright on chromium and webkit against the real `dsj ui --print-url`,
# started by ui/tests/e2e/global-setup.ts. In `verify`, not `check`. A fresh
# machine needs the browsers once: (cd ui && npx playwright install chromium webkit).
ui-e2e: _ui-modules
    cd ui && ./node_modules/.bin/playwright test

# Every frontend check FAILS without ui/node_modules rather than skipping. A
# check that switches itself off reports green in exactly the broken state:
# CI's second run went green while 14 tests skipped (.github/workflows/ci.yml).
_ui-modules:
    #!/usr/bin/env bash
    if [ ! -d ui/node_modules ]; then
        echo "ui/node_modules is missing, and the frontend checks fail rather than skip without it. Install it: (cd ui && npm ci)" >&2
        exit 1
    fi
