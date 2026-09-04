
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
