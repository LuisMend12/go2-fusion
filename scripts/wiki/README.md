# Oak wiki workspace

The wiki is a graph. [README.md](../../README.md) is the center node, Oak. It links to 7 hub pages in [docs/wiki/](../../docs/wiki/), and each hub links to one page per program. The site in `site/` shows it as a workspace: a page tree, people and recent changes on the left, the page in the middle, a 2D map on the right, and a quick switcher on `/` or `Ctrl K`. Opening a search result jumps to the first match on that page and highlights every match (Enter and Shift+Enter step through them, Esc clears). Drag the edges between the panes to resize them (double-click an edge to reset); hide the sidebar with its button or `[` and the map with the map button or `M`. The browser remembers your layout. At the bottom of every page, **Ask or change this page** copies a ready prompt for your own agent (Claude Code, Codex, ...): a question gets answered from the page and its code, and an edit ("reword this", "link this to [[Lidar]]") is made on a new branch and opened as a pull request. It guesses which one from your words, or pick it yourself. Select text on the page and press **Ask agent about this** to quote it, and type `[[` to name another page. **Ask the team instead** opens a GitHub issue. Pages are grey; a page takes a teammate's color while they have open work or an active branch on it. Under each page title are who is working there, the last change and its code; below the page, every page it connects to with the sentence that links them. Clicking a dot on the map or a link in the page opens that page in the middle and moves the map to it.

## View it locally

Needs Node.js 18+ and Python 3.8+ on your laptop (not in Docker). From the repo folder:

```shell
npm install    # once; there are no packages to download, it only sets up the commands
npm run wiki   # builds the data, serves site/ at http://localhost:4410/ and opens your browser
```

While it runs, saving README.md, a page in `docs/wiki/` or `docs/team.yml` rebuilds the data and reloads open browser tabs. If a page has a problem (say, a link to a page that does not exist), the tab keeps the last good version and shows the message. Options: `npm run wiki -- --port 4500`, `npm run wiki -- --no-open`. Stop it with Ctrl+C.

GitHub data ("who is working on what" and questions) is on when you are signed in to the GitHub CLI (`gh auth login`) or `GITHUB_TOKEN` is set; it is refreshed every 5 minutes. It only reads from GitHub. Without a token, work and questions are empty; pages, people, last changes and recent commits still build from git.

The launcher lives in [tools/oak-wiki/](../../tools/oak-wiki/) and uses only what ships with Node. It finds Python as `python3`, `python`, or on Windows `py -3`. By hand, without Node: `python3 scripts/wiki/build_graph.py`, then serve `site/` with any static server (for example `python3 -m http.server -d site 4410`).

Checks and tests: `npm run wiki:check` runs [check_wiki.py](check_wiki.py) (add `-- --base <branch>` to compare with another branch), and `npm test` runs the Python tests plus the launcher's own tests.

Without `site/graph.json` the app falls back to `site/sample-graph.json`, which has made-up people, work and questions. Open `#people/<id>` (for example `#people/max`) for a teammate's view: focus, open work, active branches, pages they have worked on and their recent changes, with their pages lit up in their color on the map (or press their name under the map).

## Add a page

Create `docs/wiki/<slug>.md` (lowercase, words joined by `-`) starting with:

```
---
title: Object detection
parent: senses          # slug of the page it hangs from; hubs use "oak"
code: [src/object_detection/**]   # optional: repo paths this page documents
---
```

Link pages with normal relative markdown links, for example `[Senses](senses.md)`. Add the new page to its parent's list. The generator stops with a message if a link points at a page that does not exist. The first sentence of the page becomes its summary.

## The team: docs/team.yml

One block per person: `id` (short, lowercase), `name`, `github` (login), `color` (their color on the site), `discord_id` (numeric Discord user id, for @mentions; empty until filled in), `focus` (one line) and optionally `past` (a list of page slugs they worked on before, like `past: [object-detection]`). Commits and GitHub activity are matched to a person by GitHub login, by the `<login>@users.noreply.github.com` email, or by git author name. Keep the simple `key: value` shape; the builder reads it without a YAML library.

## Work, questions and reviews

- Working on a page: label an issue `wiki:<slug>` and assign yourself. Open pull requests show up on their own: their changed files are matched to each page's `code:` paths (and wiki files changed directly).
- Sandbox work: any branch you push to GitHub with a commit in the last 14 days shows under "Active branches" on your tab, before there is an issue or pull request. It is matched to you by its newest commit's author, and to pages by the files it changes since it left master. Branches with nothing master lacks (already merged) are left out.
- Questions: an issue labelled `question` and `wiki:<slug>`. It counts as answered once someone other than the asker comments, or it has the label `answered`.
- Review: a pull request with requested reviewers (or the label `review`).

## graph.json v2

`build_graph.py` writes `site/graph.json` (not committed):

| Field | What it holds |
| --- | --- |
| `version`, `branch`, `base`, `published`, `generated_at`, `repo` | 2; the branch the GitHub links point at; the main branch new work starts from; whether that branch is on GitHub; build time; `owner/name` |
| `people` | `docs/team.yml`: `id`, `name`, `github`, `color`, `discord_id`, `focus`, `past`; plus `contributed` (up to 8 pages whose file or `code:` paths they committed to, most commits first, Oak left out) and `worked_on` (`past` then `contributed`, no repeats) |
| `nodes` | one per page: `id`, `title`, `parent`, `hub`, `depth`, `code`, `path`, `markdown`, `summary`, `x`, `y` (fixed layout: Oak at 0,0, hubs on a ring, pages fanned out from their hub; same input gives the same positions), `backlinks` (pages linking here), `last_change` (`sha`, `date`, `author`, `person`, `message`, or null) |
| `edges` | `source`, `target`, `kind` (`parent` or `link`) |
| `work` | open issues (`wiki:<slug>`) and open pull requests: `kind`, `number`, `title`, `url`, `author`, `person`, `assignees` (team ids), `pages`, `review_requested`, `draft`, `branch` (a pull request's head branch when it is in this repo, else null; issues have none), `updated_at` |
| `questions` | `number`, `title`, `url`, `page`, `asker`, `answered`, `answer_excerpt`, `updated_at` (closed questions with no answer are dropped) |
| `recent` | last 40 commits touching a page or its code: `sha`, `date`, `author`, `person`, `message`, `pages` |
| `branches` | remote branches other than master whose newest commit is from the last 14 days and that have commits master lacks, newest first: `name`, `person` and `author` (the newest commit's author), `last_commit` (`sha`, `date`, `message`), `ahead` (commits not on master), `pages` (pages whose file or `code:` paths cover the files changed since the branch left master; pre-`src/` paths count for today's pages), `pr` (`number`, `url` of an open pull request from this branch, else null). Read from local git: run `git fetch` first for fresh data |

`person` is a team id, or null when the author is not in `docs/team.yml`.

## Deploy and Discord

[wiki-site.yml](../../.github/workflows/wiki-site.yml) rebuilds and deploys the site to GitHub Pages on pushes to master that touch the wiki, on issue, comment and pull request changes, and every 6 hours. It always builds master.

[discord-ping.yml](../../.github/workflows/discord-ping.yml) runs [discord_ping.py](discord_ping.py) on two kinds of events:

- **Review requests** (a pull request opened ready for review, marked ready for review, or a reviewer requested): posts to #feature-revisions with Who (author, in their team color), What (title), Why, Before and After (read from the [pull request template](../../.github/pull_request_template.md) sections; "not filled in" when empty, with Why falling back to the description's first paragraph), the wiki pages touched and the link, headed "Review requested by <author> - any teammate can review". It never singles out one person. One post per request: a pull request opened with reviewers posts once, drafts wait until ready.
- **Questions** (an issue labelled `question`): posts who asked, which page, the title and link, and mentions the page owners (people with open work on that page, else its last changer).

One-time setup (Max):

1. Create a Discord webhook in #feature-revisions (channel > Edit Channel > Integrations > Webhooks > New Webhook > Copy URL) and add it as the repo secret `DISCORD_REVIEW_WEBHOOK_URL` (GitHub: Settings > Secrets and variables > Actions > New repository secret).
   Optional: make a second webhook in the channel for questions and save it as `DISCORD_QUESTIONS_WEBHOOK_URL`; without it, questions post to #feature-revisions. The older `DISCORD_WEBHOOK_URL` still works as a last fallback for both. With no secret set the ping logs "Discord not set up yet" and passes.
2. Fill each person's `discord_id` in `docs/team.yml` (Discord: Settings > Advanced > Developer Mode on, then right-click a name > Copy User ID). Without it, pings name the person instead of @mentioning them.
3. Enable Pages: Settings > Pages > Source: GitHub Actions.
