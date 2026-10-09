# Review bots: CodeRabbit and Macroscope

Two AI reviewers read every pull request on this repo. This page says what each one does,
what is set up in the repo, what only the owner can switch on, and how to turn either off.
Every claim about either tool links the official page it came from, fetched on 2026-10-09.

## Who does what

| | CodeRabbit | Macroscope |
|---|---|---|
| Main job | Line by line review of the diff, a walkthrough, linters, pre-merge checks, and the repo's writing rules | Hunting real bugs (correctness) across the whole codebase |
| How it reads code | The diff plus a sandbox of 50+ linters and scanners ([tools](https://docs.coderabbit.ai/tools/index)) | Builds a graph of the code from its syntax tree for Python and TypeScript, among others ([how it works](https://docs.macroscope.com/bug-detection-and-fixes#how-code-review-works)) |
| Config in this repo | `.coderabbit.yaml` | `.macroscope/ignore.md` and `.macroscope/correctness/correctness.md` |
| Prose (`.md`) | Reviewed, against the rules below | Skipped on purpose, so the two do not pay twice |
| Tests | Reviewed | Skipped (Macroscope's default) |
| How you pay | Per developer plan; free open source tier ([plans](https://docs.coderabbit.ai/management/plans)) | Per KB of diff reviewed, $0.05 in the default mode ([pricing](https://docs.macroscope.com/pricing)) |

## What gets reviewed, and when

| Event | CodeRabbit | Macroscope |
|---|---|---|
| A PR is opened | Yes ([auto review](https://docs.coderabbit.ai/configuration/auto-review)) | Yes, once Correctness is set to Always run ([settings](https://docs.macroscope.com/settings)) |
| A new push to an open PR | Yes, every push: the pause after 5 commits is turned off | Yes, each push can start another review ([pricing guide](https://macroscope.com/code-review/llm.txt)) |
| A draft PR | Yes (`drafts: true`) | Only if **Review Draft PRs** is on in Settings, Repos |
| A PR into any branch, not just `main` | Yes (`base_branches: [".*"]`) | Yes, unless a target branch is listed under **Skip PRs by Target Branches** |
| A push to a branch with no PR | No. Neither app reviews outside a PR | No |
| A push to `main` | No | Summarised, not reviewed, if **Summarize Commits** is on ([commit summaries](https://docs.macroscope.com/commit-summaries)) |

For work that has no PR yet, both tools ship a command line reviewer you run before pushing:
[CodeRabbit CLI](https://docs.coderabbit.ai/overview/ide-cli-review) and
[Macroscope CLI](https://docs.macroscope.com/cli). CodeRabbit's CLI can also run inside CI with
an API key ([headless CLI](https://docs.coderabbit.ai/cli/headless-cli-integration)); that is
not set up here, because the key is the owner's and each run uses review allowance.

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

## Owner-only steps

Both are GitHub apps on the owner's account, so only the owner can install them, widen them
or pay for them. `gh` cannot do it.

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

## Turning either one off

| Scope | CodeRabbit | Macroscope |
|---|---|---|
| One PR | Comment `@coderabbitai pause`, or put `@coderabbitai ignore` in the PR description ([commands](https://docs.coderabbit.ai/reference/review-commands)) | Add a skip label set in Settings, Repos ([PR labels](https://docs.macroscope.com/bug-detection-and-fixes#pr-labels)) |
| One repo | Set `reviews.auto_review.enabled: false` in `.coderabbit.yaml` ([auto review](https://docs.coderabbit.ai/configuration/auto-review)) | Settings, Repos, Features: **Manual invocation only** or **Never run** ([settings](https://docs.macroscope.com/settings)) |
| Repo config only | Delete `.coderabbit.yaml`; the account defaults apply again | Delete `.macroscope/`; Macroscope's built-in skip list applies again |
| Everywhere | Remove the app at [github.com/settings/installations](https://github.com/settings/installations) | Same page, Macroscope |
