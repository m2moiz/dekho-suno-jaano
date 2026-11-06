---
# Custom correctness instructions for Macroscope's code review.
# Docs: https://docs.macroscope.com/custom-instructions
# `include` scopes these instructions to the files below. The four fields
# that would delay or gate the review on CI (waitsFor, requires and the two
# timeouts) are left out on purpose, so every push is reviewed straight away.
include:
  - "dsj/**/*.py"
  - "ui/src/**/*.ts"
  - "ui/src/**/*.tsx"
---

**The owner's work must never be lost.** dsj writes four kinds of file that hold hours of human work: transcripts, the edit lists that hold the owner's corrections (`dsj/ui/edits.py`), reviews, and the answer keys those corrections become (`<name>.reference.json` and `<name>.reference.txt`, `dsj/ui/review.py`). Answer keys are what later models are scored against, so a wrong answer key is worse than a missing one. Report as a bug any path that can delete, truncate, overwrite or rename one of these files without keeping the old copy, or that can leave one half written after a crash, a full disk or a killed process. Writes go through `dsj/atomic.py`.

**Library upgrades are one way.** The library (`dsj/ui/store.py`) is a SQLite file that older dsj versions cannot open once it is upgraded. Report a bug if an upgrade can run without first keeping a whole copy of the old file, or if a failed or interrupted copy can stop the next start.

**No silent fallbacks.** A swallowed exception, an `or {}` default, or a guess that hides a failure is a bug here, not a style choice. The tool is meant to fail loudly so the owner sees it.

**Values from the page are not trusted.** The browser page (`ui/src/`) talks to the server in `dsj/ui/`. Anything the page sends that ends up in an answer key or a review must be checked on the server (issue #257).

**macOS only.** dsj runs on Apple Silicon with MLX. Do not report a missing Linux or Windows code path as a bug.
