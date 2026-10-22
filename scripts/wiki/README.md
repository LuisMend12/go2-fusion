# Oak wiki graph site

The wiki is a graph. [README.md](../../README.md) is the center node, Oak. It links to 7 hub pages in [docs/wiki/](../../docs/wiki/), and each hub links to one page per program.

## View it locally

```shell
python3 scripts/wiki/build_graph.py && python3 -m http.server -d site 8765
```

Then open http://localhost:8765/. Click a node to read its page; links in the page move you through the graph.

Without `site/graph.json` the app falls back to `site/sample-graph.json`, which has made-up people, work and questions. Add `?person=<id>` to the URL to start with a teammate's work highlighted.

## Add a page

Create `docs/wiki/<slug>.md` (lowercase, words joined by `-`) starting with:

```
---
title: Object detection
parent: senses          # slug of the page it hangs from; hubs use "oak"
code: [src/object_detection/**]   # optional: repo paths this page documents
---
```

Link pages with normal relative markdown links, for example `[Senses](senses.md)`. Add the new page to its parent's list. The generator stops with a message if a link points at a page that does not exist.

## Active work

Label a GitHub issue `wiki:<slug>` (for example `wiki:slam`) and assign it. On the next deploy, that node shows a badge and the panel says who is working on what. Locally this only works with `GITHUB_TOKEN` and `GITHUB_REPOSITORY` set.

## Deploy

[.github/workflows/wiki-site.yml](../../.github/workflows/wiki-site.yml) rebuilds and deploys the site to GitHub Pages on every push to master that touches the wiki. Pages must be enabled once: Settings > Pages > Source: GitHub Actions.
