---
name: wiki-keeper
description: Keep the team wiki (README.md + docs/wiki/) true to the code. Use whenever code under src/, host_tools/ or docker/ changes, when a package is added or removed, before opening a pull request, when starting a task (to claim it on the wiki graph), or when someone asks to update or check the wiki.
---

# Wiki keeper

The wiki is a graph: README.md is the center page "Oak", 7 hub pages hang off it, and each program has one page under a hub. Pages live in `docs/wiki/<slug>.md`. A pull request check (`.github/workflows/wiki-check.yml`) fails when the wiki falls behind the code, so keep it current as you go.

Every page starts with front matter:

```
---
title: Object detection
parent: senses                    # hub pages use "oak"
code: [src/object_detection/**]   # optional: the repo paths this page documents
---
```

## When starting a task

So the wiki graph shows who is working on what:

1. Find an open GitHub issue for the task, or open one: `gh issue list --search "<words>"`, `gh issue create`.
2. Label it `wiki:<slug>` for the page it touches (create the label if missing: `gh label create wiki:<slug>`), and assign yourself: `gh issue edit <n> --add-label wiki:<slug> --add-assignee @me`.

If `gh` is not signed in, tell the human the exact commands instead of skipping this.

## Before opening a pull request (or whenever code changed)

1. `git fetch origin`, then run `python3 scripts/wiki/check_wiki.py` (it compares against origin/master and includes uncommitted work).
2. For each page it flags, read the diff for that page's code (`git diff origin/master...HEAD -- <paths>`) and update the page in plain English a college freshman would follow:
   - what the program does for Oak,
   - what it uses (topics, sensors, other programs, hardware),
   - how it breaks (known failure modes and what they look like).
   Not code internals: no function names or line-by-line walkthroughs.
3. New package in `src/`: create `docs/wiki/<slug>.md` with title, parent (its hub) and `code: [src/<package>/**]`, then link it from the hub page.
   Removed package: delete its page and its link from the hub.
4. Never invent facts. If you don't know something (a limit, an owner, a failure mode), write `TODO(owner): <question>` instead of guessing.
5. Keep pages short: a few short paragraphs or bullets. Link to other pages rather than repeating them.
6. Re-run the checker until it prints "Wiki check passed".

If a change truly does not affect what any page says (a rename, a comment, a refactor with identical behavior), add this line to the pull request description instead of editing the page:

```
wiki: no change needed - <reason>
```

## What the checker checks

- every page has a title and a parent that exists, and every link to a .md file works;
- following parents from any page reaches README.md (no orphans, no loops);
- pages whose `code:` paths changed were also changed (unless the pull request has the line above);
- every folder in `src/` is claimed by some page's `code:`.

Run the checker's own tests with `python3 -m unittest discover -s scripts/wiki/tests`.
