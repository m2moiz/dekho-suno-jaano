# Review bots: who reads a pull request here

Five tools look at every pull request on this repo. Three review it, one fixes on request,
and one measures test coverage. This page says what each does, when it runs, what it costs,
what is set up in the repo, what only the owner can switch on, and how to turn each off.
Every claim about a tool links the official page it came from, fetched on 2026-10-09.

Agents, Claude among them, write most of the code here. So the reviewers that run on their
own are the ones from other vendors, and Claude is kept for fixing, on request.

## Who does what

| Tool | Runs | Its job | Left to the others |
|---|---|---|---|
| CodeRabbit | On its own, every push, drafts too | Line by line review, 50+ linters, the repo's rules, prose, the PR summary, pre-merge checks | Nothing; it is the broad pass |
| Macroscope | On its own, every push (once Correctness is set to Always run) | Hunts correctness bugs in `dsj/` and `ui/src/` | Tests, Markdown, `scratch/`, the built page |
| Cursor Bugbot | On its own, once per PR, when it is not a draft; `bugbot run` for another pass | A second bug hunt from another vendor, aimed where Macroscope does not look: tests that cannot fail, lost work, security, workflows and `just` scripts | Style, the summary, fixes |
| Claude | Only when the owner writes `@claude` | The "fix it" tool: explain a finding, push a fix to the PR branch | Reviewing; it wrote the code |
| Codecov | On its own, every push | Coverage of the lines the PR changes, and of the package; one PR comment, only when coverage drops | Judging the code |

How to read a PR with all five on it:

1. Wait for CI. `check` and `install-gate` are the only required checks; Codecov's two
   statuses are advice.
2. Read CodeRabbit's walkthrough first. It is the summary; Bugbot's is switched off in its settings.
3. Bug findings come from Macroscope (every push) and Bugbot (once). When both flag the same
   thing, that is agreement between two vendors, not noise.
4. To fix a finding, reply on the PR: `@claude fix the bug Bugbot found in dsj/ui/review.py`.
   Claude pushes a commit, CI runs on it, and CodeRabbit and Macroscope re-review the push.

## What gets reviewed, and when

| Event | CodeRabbit | Macroscope | Bugbot | Claude | Codecov |
|---|---|---|---|---|---|
| A PR is opened | Yes ([auto review](https://docs.coderabbit.ai/configuration/auto-review)) | Yes, once Correctness is set to Always run ([settings](https://docs.macroscope.com/settings)) | Yes ([Bugbot](https://cursor.com/docs/bugbot)) | No | Yes, from the CI run on the push |
| A new push to an open PR | Yes, every push: the pause after 5 commits is turned off | Yes, each push can start another review ([pricing guide](https://macroscope.com/code-review/llm.txt)) | No: `frequency: oncePerPr` | No | Yes |
| A draft PR | Yes (`drafts: true`) | Only if **Review Draft PRs** is on in Settings, Repos | No: `drafts: false` | Only if asked | Yes |
| A comment with `@claude` from the owner | No | No | No | Yes | No |
| A comment `bugbot run` or `cursor review` | No | No | Yes, a fresh review | No | No |
| A push to a branch with no PR | No | No | No | No | Coverage is uploaded, no comment |
| A push to `main` | No | Summarised, not reviewed, if **Summarize Commits** is on ([commit summaries](https://docs.macroscope.com/commit-summaries)) | No | No | Coverage is uploaded; it is the base PRs compare against |

For work that has no PR yet, CodeRabbit and Macroscope ship a command line reviewer you run
before pushing: [CodeRabbit CLI](https://docs.coderabbit.ai/overview/ide-cli-review) and
[Macroscope CLI](https://docs.macroscope.com/cli). Claude Code has `/code-review` in a local
session ([review a diff locally](https://code.claude.com/docs/en/code-review#review-a-diff-locally)),
which uses the same Claude allowance as everything else.

## What it costs

Volume: 12 PRs were merged in the 30 days to 2026-10-09 (`gh pr list --state merged`), so
10 to 20 a month is the working figure. The repo is public.

| Tool | How it bills | Already paid | Expected per month here | The one cap |
|---|---|---|---|---|
| CodeRabbit | A plan per developer, no usage charge ([plans](https://docs.coderabbit.ai/management/plans)) | Trial (PR #280 showed `Plan: Advanced`) | $0 on the open source tier, where a repo under 10 stars is reviewed only when asked; $24 a month billed yearly, or $30 monthly, for Essentials | Which plan is chosen at [app.coderabbit.ai/settings/subscription](https://app.coderabbit.ai/settings/subscription) |
| Macroscope | $0.05 per KB of diff reviewed ([pricing](https://docs.macroscope.com/pricing)) | $100 free usage for a new workspace ([llms.txt](https://macroscope.com/llms.txt)) | About $60 for one pass over each PR, more when pushes are re-reviewed. Estimate: the 12 PRs above had 1,225 KB of changed code lines, counting `gh pr diff` output with tests, Markdown, `scratch/`, the built page, JSON and lock files left out. PR #280 alone was 518 KB, about $26 | Monthly spend limit, Settings, Billing ([spend controls](https://docs.macroscope.com/pricing#spend-controls)) |
| Cursor Bugbot | Usage: "for Individuals, it will bill from included usage"; the average run is $1.00 to $1.50 ([May 2026 Bugbot changes](https://cursor.com/blog/may-2026-bugbot-changes)). Included usage goes first, then on-demand spend ([Bugbot](https://cursor.com/docs/bugbot)) | The Cursor subscription | $12 to $18 of the plan's included usage at one run per PR for 12 PRs. That usage is shared with work in the editor. No new money unless on-demand usage is on | `triggers.frequency: oncePerPr` in the repo; and if on-demand usage is on, a Monthly Limit on the Spending tab at [cursor.com/dashboard/spending](https://cursor.com/dashboard/spending) ([spend limits](https://cursor.com/help/account-and-billing/spend-limits)) |
| Claude | The OAuth token "authenticates with your Claude subscription" ([authentication](https://code.claude.com/docs/en/authentication#generate-a-long-lived-token)); "runs use your Claude subscription instead of API billing" ([manage costs](https://code.claude.com/docs/en/github-actions#manage-costs)) | Claude Max | $0 new money. Each `@claude` run uses the Max weekly allowance, so it only runs when asked | Runs only on `@claude` from the owner, `--max-turns 15`, 20 minute job timeout, one run per PR at a time (`.github/workflows/claude.yml`) |
| Codecov | Free: the Developer plan "is best for open-source projects and offers unlimited uploads" ([pricing](https://about.codecov.io/pricing/)) | Nothing to pay | $0 | Nothing to cap |
| GitHub Actions | "free ... for public repositories that use standard GitHub-hosted runners" ([Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)) | | $0 | |

Two paid options were left out on purpose. Claude's managed **Code Review** service is for
Team and Enterprise plans only, billed through usage credits at $15 to $25 a review on
average, outside the plan's included usage
([Code Review](https://code.claude.com/docs/en/code-review)); a Max plan cannot use it.
Bugbot **Autofix** starts a Cloud Agent "billed at your plan rates" and needs on-demand
usage on ([Bugbot](https://cursor.com/docs/bugbot)); `@claude` does that job here.

If Macroscope's bill is more than the owner wants, the cheapest change is to set its
Correctness to **Manual invocation only** and let Bugbot be the one automatic bug hunter, or
switch Bugbot to `everyPush` so it covers pushes too, at $1.00 to $1.50 a run of included
usage.

## What is set up in the repo

`.coderabbit.yaml` (checked against CodeRabbit's schema,
`https://coderabbit.ai/integrations/schema.v2.json`, before it was committed):

1. **Assertive profile, British English, a plain tone.** No em or en dashes, findings lead
   with what breaks, code cited by `rg` pattern.
2. **Every PR, every push, drafts included, any target branch.**
3. **Request changes workflow on.** CodeRabbit marks the PR "changes requested" while it has
   open findings and approves once they are resolved and no pre-merge check fails
   ([request changes workflow](https://docs.coderabbit.ai/pr-reviews/request-changes-workflow)).
   The `main` ruleset requires 0 approvals. Whether GitHub then still lets a PR merge past a
   CodeRabbit "changes requested" review has not been tested here.
4. **Path instructions** carrying the rules from `AGENTS.md` and this folder's `runbook.md`:
   data safety for transcripts, corrections and answer keys; `just check` as the gate; tests
   first; the generated `dsj/ui/static/` and `ui/src/api/schema.d.ts` never hand-edited; the
   TypeScript pin and the `@base-ui/react` name.
5. **Four custom pre-merge checks:** generated files match their sources (error), behaviour
   changes ship with a test, no em or en dashes in added prose, code cited by `rg` pattern
   (warnings). The built-in docstring check is off, because ruff already enforces docstrings.
6. **Short walkthrough:** summary moved out of the PR description into the walkthrough,
   five bullets at most, no sequence diagrams, no suggested reviewers.
7. **Code guidelines:** `AGENTS.md` is read automatically
   ([code guidelines](https://docs.coderabbit.ai/knowledge-base/code-guidelines)); the
   runbook and `DESIGN.md` are added.

`.macroscope/`:

1. `ignore.md` copies Macroscope's built-in skip list (a custom file replaces it, it does not
   add to it) and adds the built page, `.md` files, `scratch/`, `.impeccable/` and `.beads/`
   ([ignore file](https://docs.macroscope.com/bug-detection-and-fixes#macroscope-ignore)).
2. `correctness/correctness.md` tells the bug hunt what matters most here: never lose the
   owner's transcripts, corrections or answer keys; library upgrades keep a whole backup; no
   silent fallbacks; macOS only ([custom instructions](https://docs.macroscope.com/custom-instructions)).

Bugbot (**held back, not committed**): two files, `.cursor/config/bugbot.yaml` and
`.cursor/BUGBOT.md`, are written out in full under
[Bugbot repo files](#bugbot-repo-files-waiting-for-the-owner) below. The machine's
`git-ai-files-guard` hook blocks `.cursor/` files from entering a public repo's history, and
letting them in here is the owner's call, so this PR does not carry them. Until they land,
Bugbot runs on the dashboard settings in the owner-only steps, which give the same once per
PR behaviour.

1. `config/bugbot.yaml`: one review per PR (`triggers.frequency: oncePerPr`), drafts
   skipped, default effort, the PR summary off (CodeRabbit writes it), Autofix off. Bugbot
   reads this file from the PR's **base** branch, so it takes effect once it is on `main`.
   The PR author's personal settings outrank it ([Bugbot](https://cursor.com/docs/bugbot)).
2. `BUGBOT.md`: who covers what, so Bugbot looks where the others do not: tests that would
   pass with the change reverted, lost transcripts and answer keys, security, and the
   workflows and `scratch/` scripts. It also says what not to report. Cursor's own rules in
   `.cursor/rules/` are not read by Bugbot, which is why this is a separate file.

`.github/workflows/claude.yml` (Claude, on request):

1. Starts only for a PR comment, inline comment or review that contains `@claude` and comes
   from the owner, a member or a collaborator. The action also refuses users without write
   access and any bot author not listed in `allowed_bots`, so CodeRabbit or Bugbot cannot
   start it ([who can trigger runs](https://code.claude.com/docs/en/github-actions#who-can-trigger-runs)).
2. No `prompt` input, so the action runs in interactive mode: it answers the request in a
   comment and can push commits to the PR branch
   ([interactive and automation modes](https://code.claude.com/docs/en/github-actions#interactive-and-automation-modes)).
   No automatic review workflow is installed.
3. Capped as the docs advise: `--max-turns 15`, `timeout-minutes: 20`, and a concurrency
   group so two requests on one PR queue instead of racing
   ([manage costs](https://code.claude.com/docs/en/github-actions#manage-costs)).
4. Acts as the Claude GitHub App (no `github_token` input), so CI runs on Claude's commits
   ([troubleshooting](https://code.claude.com/docs/en/github-actions#ci-not-running-on-claudes-commits)).
   It runs on Linux and cannot run `just check`, which needs a Mac; CI runs it on the push.
5. Pinned to `anthropics/claude-code-action@v1.0.247` and `actions/checkout@v7.0.1`, both
   checked to resolve.

`codecov.yml` and the `check` job in `.github/workflows/ci.yml` (Codecov):

1. The `no test may silently skip` step already runs the fast suite a second time. It now
   adds `--cov=dsj --cov-report=xml`, so coverage needs no extra run of the suite. Measured
   locally on 2026-10-09: 160 s without coverage, 147 s and 139 s with it, so the cost is
   within run to run noise and well under the one minute allowed. The step's guard against
   skipped tests still reads only pytest's summary line: the XML report adds one line,
   "Coverage XML written to file", and no line that says "skipped".
2. A new last step uploads `coverage.xml` with `codecov/codecov-action@v7.1.1` and
   `use_oidc: true`, so no Codecov token is stored anywhere
   ([using OIDC](https://github.com/codecov/codecov-action#using-oidc)). It runs on push
   events only, which already include every PR branch here, so each commit is sent once. A
   failed upload does not fail CI.
3. The upload is the fast lane: about 96 percent locally (4,769 statements, 212 missed).
   `just verify`, with the slow tests, stays the full measurement. Code only the slow tests
   reach shows as uncovered on Codecov.
4. `codecov.yml`: a project status that compares with the base commit and allows a 1 percent
   drop, a patch status at 90 percent (the floor `just verify` uses), and one PR comment,
   edited in place, posted only when coverage drops or the PR adds lines no test runs
   ([commit status](https://docs.codecov.com/docs/commit-status),
   [PR comments](https://docs.codecov.com/docs/pull-request-comments)). The file passed
   `curl --data-binary @codecov.yml https://codecov.io/validate`
   ([codecov.yml](https://docs.codecov.com/docs/codecov-yaml)). Neither status is a required
   check.

These are configuration changes; no Python or `ui/` source changed, so `just check` was not
run for them. CI runs it on the push, which is also the first real run of the coverage step.

## Owner-only steps

Every step here is on the owner's own accounts, so an agent cannot do it. `gh` can set a
secret, but the token has to come from the owner's own `claude setup-token`.

**CodeRabbit**

- [ ] **Widen the app to all repositories.** Open
  [github.com/settings/installations](https://github.com/settings/installations), click
  **Configure** next to CodeRabbit, under **Repository access** pick **All repositories**,
  click **Save**. "All repositories" also covers repos made later
  ([GitHub install](https://docs.coderabbit.ai/platforms/github-com)).
- [ ] **Check which plan the account is on.** The review on PR #280 says
  `Plan: Advanced`. New accounts start on a 14 day Advanced trial and drop to Free unless
  they subscribe ([plans](https://docs.coderabbit.ai/management/plans)). Look at
  [app.coderabbit.ai/settings/subscription](https://app.coderabbit.ai/settings/subscription).
- [ ] **Decide what happens after the trial.** On the open source tier, public repos with
  fewer than 10 stars are only reviewed when asked: click **Trigger review** in the
  CodeRabbit status comment, or comment `@coderabbitai review`
  ([plans, rate limits](https://docs.coderabbit.ai/management/plans#rate-limits)). This repo
  has 0 stars. Automatic review of every push needs a paid plan (Essentials is $24 a month
  billed yearly, or $30 monthly, per the same page).

**Macroscope**

- [ ] **Sign up and connect GitHub.** Go to
  [app.macroscope.com/login](https://app.macroscope.com/login), authorize Macroscope in
  GitHub, and pick the repositories (choose all)
  ([getting started](https://docs.macroscope.com/setup-instructions)).
- [ ] **Pay or apply.** Setup ends with a Stripe checkout; new workspaces get $100 of usage
  free ([llms.txt](https://macroscope.com/llms.txt)). Free credits for non-commercial open
  source projects: apply on [macroscope.com/open-source](https://macroscope.com/open-source)
  (the form is [here](https://form.typeform.com/to/F5TAQUxn)). The licence here is AGPL and
  the project is personal and non-commercial; they say they prioritise projects with an
  active community, so approval is not certain.
- [ ] **Turn review on.** In Settings, Repos, Features, set **Correctness** to **Always run**
  for these repos, and under **Defaults** for repos added later. New workspaces start with it
  off ([settings](https://docs.macroscope.com/settings)).
- [ ] **Turn on Review Draft PRs** in Settings, Repos, to match CodeRabbit.
- [ ] **Leave Summarize PRs on GitHub off.** CodeRabbit already writes the summary.
- [ ] **Decide on Summarize Commits.** It is the only thing either tool does with a push to
  `main`, at $0.05 a commit ([pricing](https://docs.macroscope.com/pricing)).
- [ ] **Set a monthly spend limit** in Settings, Billing. It is the one hard ceiling; the
  default caps are $10 a review and $50 a PR
  ([spend controls](https://docs.macroscope.com/pricing#spend-controls)).

**Claude**

- [ ] **Give the Claude app this repo.** Open
  [github.com/settings/installations](https://github.com/settings/installations), click
  **Configure** next to Claude, and pick **All repositories** or add this one. The action
  needs its Contents, Issues and Pull requests access
  ([manual setup](https://code.claude.com/docs/en/github-actions#manual-setup)).
- [ ] **Make the token, in your own terminal.** Run `claude setup-token`, approve in the
  browser, and copy the token it prints. It lasts one year and can only make model requests
  ([long-lived token](https://code.claude.com/docs/en/authentication#generate-a-long-lived-token)).
  Put a reminder for next October.
- [ ] **Store it as a repository secret.** Run
  `gh secret set CLAUDE_CODE_OAUTH_TOKEN --repo m2moiz/dekho-suno-jaano` and paste the token
  when asked, or add it on
  [the repo's Actions secrets page](https://github.com/m2moiz/dekho-suno-jaano/settings/secrets/actions).
  For another public repo, set the same secret there and copy `claude.yml` in. The docs
  describe repository and organization secrets
  ([set up for an organization](https://code.claude.com/docs/en/github-actions#set-up-for-an-organization));
  a personal account uses one per repo.
- [ ] **Do not run `/install-github-app` here.** It writes its own `claude.yml` and offers an
  automatic review workflow ([quick setup](https://code.claude.com/docs/en/github-actions#quick-setup));
  that would put the same Claude that wrote the code on every PR, on the Max allowance.
- [ ] **Try it** once the workflow is on `main`: comment `@claude what does this PR change?`
  on an open PR. A top-level PR comment is an `issue_comment` event, which "will only trigger
  a workflow run if the workflow file exists on the default branch"
  ([events that trigger workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)),
  so before merge only an inline review comment would reach it.

**Cursor Bugbot**

- [ ] **Turn it on for the repos.** Open
  [cursor.com/automations/from-cursor/bugbot](https://cursor.com/automations/from-cursor/bugbot),
  connect GitHub if asked, and enable Bugbot on this repo and the other public ones. For an
  individual plan, "Bugbot runs only on PRs you author"
  ([Bugbot](https://cursor.com/docs/bugbot)); agent PRs here are opened as `m2moiz`.
- [ ] **Set the personal settings.** In the same place: **Run only when mentioned** off,
  **Run only once** on, **PR Summaries** off. These are what keep Bugbot to one review per
  PR while the repo files are held back, and they cover every repo that has no such file.
  Personal settings outrank `.cursor/config/bugbot.yaml` ([Bugbot](https://cursor.com/docs/bugbot)).
- [ ] **Decide on the two Bugbot repo files.** To commit them, copy them out of
  [Bugbot repo files](#bugbot-repo-files-waiting-for-the-owner) and commit them yourself
  with the hook's documented override: `ALLOW_AI_WORKFLOW_FILES=1 git commit ...`. Without
  them Bugbot still works, with no repo-specific rules.
- [ ] **Check the billing.** Bugbot moved from a $40 seat to usage billing at the first
  renewal after 8 June 2026, and existing customers can switch early in the dashboard
  ([May 2026 Bugbot changes](https://cursor.com/blog/may-2026-bugbot-changes)). Make sure no
  $40 Bugbot seat is still being charged. Usage shows at
  [cursor.com/dashboard/usage](https://cursor.com/dashboard/usage).
- [ ] **If on-demand usage is on, set a Monthly Limit** on the Spending tab,
  [cursor.com/dashboard/spending](https://cursor.com/dashboard/spending)
  ([spend limits](https://cursor.com/help/account-and-billing/spend-limits)).
- [ ] **Leave Autofix off** in the dashboard. The repo file can lower the dashboard's Autofix
  mode but cannot raise it.

**Codecov**

- [ ] **Log in once** at [app.codecov.io](https://app.codecov.io) with GitHub and check
  `dekho-suno-jaano` is listed ([quick start](https://docs.codecov.com/docs/quick-start)).
  The Codecov app is already installed; widen it to all repositories on
  [github.com/settings/installations](https://github.com/settings/installations) if it is not.
- [ ] **Create no token.** CI authenticates with OIDC. Only if the first upload fails with an
  authentication error: copy the repository token from the repo's **Configuration** tab in
  Codecov, store it as the `CODECOV_TOKEN` secret, and replace `use_oidc: true` with
  `token: ${{ secrets.CODECOV_TOKEN }}` in `ci.yml`
  ([tokens](https://docs.codecov.com/docs/codecov-tokens)).
- [ ] **For other public repos**, add the same upload step to their CI and copy
  `codecov.yml`. Codecov reads it from the root, `dev/` or `.github/`
  ([codecov.yml](https://docs.codecov.com/docs/codecov-yaml)).

Codecov's own AI reviewer is deprecated
([Codecov AI](https://docs.codecov.com/docs/beta-codecov-ai)); its successor is a separate
Sentry product and is not set up.

## Bugbot repo files, waiting for the owner

Held back from this PR by the `git-ai-files-guard` hook (see the owner-only steps).
Both were checked against [cursor.com/docs/bugbot](https://cursor.com/docs/bugbot); the YAML
parses.

`.cursor/config/bugbot.yaml`:

```yaml
# Cursor Bugbot settings for dekho-suno-jaano. docs/review-bots.md explains
# the setup and where Bugbot sits next to the other reviewers.
#
# Every key is from https://cursor.com/docs/bugbot (fetched 2026-10-09).
# Bugbot reads this file from the PR's BASE branch, so a change here takes
# effect only once it is on main. A PR cannot change how it is reviewed.

version: 1

triggers:
  # Drafts are work in progress; review once the PR is ready.
  drafts: false
  # One review per PR, not one per push. Each run draws on the Cursor plan's
  # usage (about $1.00 to $1.50 a run, https://cursor.com/blog/may-2026-bugbot-changes).
  # CodeRabbit and Macroscope already re-review every push. Comment
  # `bugbot run` on the PR for another pass after a large change.
  frequency: oncePerPr

review:
  effort: default

# CodeRabbit writes the PR summary. A second one is noise.
prSummary:
  mode: disabled

# Off. Autofix starts a Cloud Agent billed as on-demand usage, and fixes
# here go through `@claude` on the PR instead.
autofix:
  mode: disabled
```

`.cursor/BUGBOT.md`:

````markdown
# Review rules for dekho-suno-jaano

dsj is a command line tool and a local web page that turn screen recordings
into timestamped transcripts on a Mac. Coding agents write most of the code.
Your review is one of four, so stay in your lane:

- CodeRabbit reviews every push for style, lint, prose and the repo's rules.
- Macroscope hunts correctness bugs in `dsj/` and `ui/src/` on every push, and
  skips tests, Markdown and the built page.
- You run once per PR. Look where the others do not.

## What to look for, in this order

1. **Lost work.** Any path that can delete, truncate, overwrite or rename a
   transcript, an edit list, a review or an answer key
   (`<name>.reference.json`, `<name>.reference.txt`) without keeping the old
   copy, or leave one half written after a crash or a full disk. Writes go
   through `dsj/atomic.py`.
2. **Tests that cannot fail.** Macroscope skips tests, so you are the only bug
   hunter reading them. Flag a test that would still pass if the change it
   covers were reverted, a test that asserts on a mock instead of behaviour,
   and a skip or `xfail` on the very condition the test exists to catch.
3. **Security.** Values the browser page sends to `dsj/ui/` must be checked on
   the server before they reach an answer key or a review. Shell commands
   built from file names. Secrets in workflow files.
4. **Glue code.** Macroscope's instructions cover `dsj/` and `ui/src/` only and
   it skips `scratch/`, so read `.github/workflows/`, the `justfile` and the
   `scratch/*.py` scripts that `just` runs for logic bugs.

## What not to report

- Style, naming, formatting, docstrings, typos: ruff, pyright and CodeRabbit
  cover them.
- Anything in `dsj/ui/static/` or `ui/src/api/schema.d.ts`. Both are
  generated; `just check` fails when they are stale.
- Missing Linux or Windows support. dsj is macOS only, on purpose.

## How to write a finding

Report only bugs you are confident break behaviour. Lead with what breaks and
for whom. Plain English, no em or en dashes. Cite code by an `rg` pattern that
finds it, for example `rg -n 'def write_status' dsj/suno.py`, not by a line
number alone.
````

## The other apps on the account

| App | Reviews code? | Cost of leaving it installed |
|---|---|---|
| lovable.dev | No. It syncs a Lovable project with one GitHub repo and can open PRs ([GitHub integration](https://docs.lovable.dev/integrations/github)) | The page names no charge for the GitHub connection, which is "available on all plans" |
| Runpod | No. It builds a container image from a repo and deploys it to a Runpod endpoint ([GitHub integration](https://docs.runpod.io/serverless/workers/github-integration)) | The page has no billing information; it acts only on repos linked to an endpoint |
| Vercel | Not here. It deploys repos connected to a Vercel project, and its Agent Code Review is "available on Enterprise and Pro plans" and reviews "repositories connected to your Vercel projects" ([Vercel for GitHub](https://vercel.com/docs/git/vercel-for-github), [Code Review](https://vercel.com/docs/agent/pr-review)). dsj is a Mac tool, not deployed to Vercel | The pages name no charge for the install; Agent reviews are billed per token |

Nothing was uninstalled.

## Five habits that get the most out of CodeRabbit

1. **Reply on the line, so it learns.** When a finding is wrong for this repo, reply to that
   comment with `@coderabbitai` and say why. It stores a learning and applies it to later
   reviews. For a one-off exception, resolve the comment instead
   ([learnings](https://docs.coderabbit.ai/knowledge-base/learnings)). Macroscope learns the
   same way from replies and from a thumbs up or down
   ([code review](https://docs.macroscope.com/bug-detection-and-fixes)).
2. **Hand the "Prompt for AI Agents" block to the agent.** Each finding carries one; it tells
   the agent to check the finding against the code first and fix only what still holds, as
   seen on [PR #280](https://github.com/m2moiz/dekho-suno-jaano/pull/280#discussion_r4229445408)
   ([configuration, enable_prompt_for_ai_agents](https://docs.coderabbit.ai/reference/configuration)).
3. **Drive it with commands.** `@coderabbitai review` for new pushes, `full review` to start
   over, `pause` and `resume` on a busy branch, `rate limit` to see what is left,
   `configuration` to see the settings in force
   ([commands](https://docs.coderabbit.ai/reference/review-commands)).
4. **Grow the path instructions from what it misses.** After a few weeks of reviews, comment
   `@coderabbitai emit path instructions`; it opens a PR adding what it has learned to
   `.coderabbit.yaml` without overwriting what is there
   ([path instructions](https://docs.coderabbit.ai/configuration/path-instructions)).
5. **Treat the pre-merge checks as part of the gate.** A failing check holds back approval.
   Fix it, or say in the PR description why it does not apply. `@coderabbitai approve`
   overrides the checks, so keep it for real exceptions
   ([pre-merge checks](https://docs.coderabbit.ai/pr-reviews/pre-merge-checks)).

## Turning each one off

| Scope | CodeRabbit | Macroscope | Bugbot | Claude | Codecov |
|---|---|---|---|---|---|
| One PR | Comment `@coderabbitai pause`, or put `@coderabbitai ignore` in the PR description ([commands](https://docs.coderabbit.ai/reference/review-commands)) | Add a skip label set in Settings, Repos ([PR labels](https://docs.macroscope.com/bug-detection-and-fixes#pr-labels)) | Keep the PR a draft (`drafts: false`) | Do not write `@claude` | Nothing to do; its statuses are not required |
| One repo | Set `reviews.auto_review.enabled: false` in `.coderabbit.yaml` ([auto review](https://docs.coderabbit.ai/configuration/auto-review)) | Settings, Repos, Features: **Manual invocation only** or **Never run** ([settings](https://docs.macroscope.com/settings)) | Disable the repo in the installations list at [cursor.com/automations/from-cursor/bugbot](https://cursor.com/automations/from-cursor/bugbot) | Delete `.github/workflows/claude.yml` and the `CLAUDE_CODE_OAUTH_TOKEN` secret ([uninstall](https://code.claude.com/docs/en/github-actions#uninstall)) | Delete the upload step from `ci.yml` and delete `codecov.yml` |
| Repo config only | Delete `.coderabbit.yaml`; the account defaults apply again | Delete `.macroscope/`; Macroscope's built-in skip list applies again | Not committed yet; once it is, delete `.cursor/config/bugbot.yaml` and `.cursor/BUGBOT.md` | Not applicable | Delete `codecov.yml`; Codecov's defaults apply |
| Everywhere | Remove the app at [github.com/settings/installations](https://github.com/settings/installations) | Same page, Macroscope | Turn Bugbot off in the Cursor dashboard; the Cursor app may serve other features | Remove the secret from each repo. Uninstall the Claude app only if no other Claude feature uses it. A deleted secret's token stays valid | Same page, Codecov |
