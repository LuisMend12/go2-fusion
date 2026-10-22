#!/usr/bin/env python3
"""Build site/graph.json from the wiki pages.

Reads README.md (the center node "oak") and docs/wiki/*.md, and writes
site/graph.json for the 3D graph site in site/index.html.

    python3 scripts/wiki/build_graph.py && python3 -m http.server -d site 8765

Then open http://localhost:8765/.

Optional: with GITHUB_TOKEN and GITHUB_REPOSITORY set (as in GitHub Actions),
open issues labelled "wiki:<slug>" are attached to that page as active work.
Without a token this step is skipped.

Standard library only.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WIKI = ROOT / "docs" / "wiki"
OUT = ROOT / "site" / "graph.json"
CENTER = "oak"

# [text](target) but not images ![alt](src)
LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
FENCE_RE = re.compile(r"```.*?```", re.S)


def fail(msg):
    print(f"build_graph: {msg}", file=sys.stderr)
    sys.exit(1)


def parse_front_matter(text, path):
    """Return (fields, body). Handles 'key: value' and 'key: [a, b]' lines."""
    if not text.startswith("---"):
        return None, text
    end = text.find("\n---", 3)
    if end == -1:
        fail(f"{path} starts a front matter block with '---' but never closes it.")
    block = text[3:end].strip("\n")
    body = text[end + 4:].lstrip("\n")
    fields = {}
    for line in block.splitlines():
        line = line.split(" #", 1)[0].rstrip()  # drop trailing comments
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            fail(f"{path}: cannot read front matter line '{line}'.")
        key, value = line.split(":", 1)
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            value = [v.strip().strip("'\"") for v in value[1:-1].split(",") if v.strip()]
        else:
            value = value.strip("'\"")
        fields[key.strip()] = value
    return fields, body


def rel(path):
    return path.relative_to(ROOT).as_posix()


def load_pages():
    pages = {}
    readme = ROOT / "README.md"
    pages[CENTER] = {
        "id": CENTER,
        "title": "Oak",
        "parent": None,
        "code": [],
        "file": readme,
        "markdown": readme.read_text(encoding="utf-8"),
    }
    for path in sorted(WIKI.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        fields, body = parse_front_matter(text, rel(path))
        if fields is None:
            continue  # not a wiki page (no front matter)
        slug = path.stem
        if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", slug):
            fail(f"{rel(path)}: page names must be lowercase words joined by '-'.")
        if "title" not in fields or "parent" not in fields:
            fail(f"{rel(path)}: front matter needs both 'title' and 'parent'.")
        code = fields.get("code", [])
        if isinstance(code, str):
            code = [code] if code else []
        pages[slug] = {
            "id": slug,
            "title": fields["title"],
            "parent": fields["parent"],
            "code": code,
            "file": path,
            "markdown": body,
        }
    return pages


def page_for(path, pages):
    """Map a resolved file path to a page id, or None if it is not a page."""
    for pid, page in pages.items():
        if page["file"].resolve() == path:
            return pid
    return None


def collect_edges(pages):
    edges = []
    seen = set()

    def add(source, target, kind):
        key = (source, target)
        if source == target or key in seen:
            return
        seen.add(key)
        edges.append({"source": source, "target": target, "kind": kind})

    for pid, page in pages.items():
        parent = page["parent"]
        if parent is not None:
            if parent not in pages:
                fail(f"{rel(page['file'])} says its parent is '{parent}', but there is no page called '{parent}'.")
            add(parent, pid, "parent")

    for pid, page in pages.items():
        text = FENCE_RE.sub("", page["markdown"])
        for target in LINK_RE.findall(text):
            if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I) or target.startswith("#"):
                continue  # web link or same-page anchor
            target = target.split("#", 1)[0]
            if not target.endswith(".md"):
                continue
            resolved = (page["file"].parent / target).resolve()
            tid = page_for(resolved, pages)
            if tid is None:
                in_wiki = resolved.parent == WIKI.resolve() or resolved == (ROOT / "README.md").resolve()
                if in_wiki or not resolved.exists():
                    fail(f"{rel(page['file'])} links to '{target}', but that page does not exist.")
                continue  # a normal repo doc, not a wiki page
            if (pid, tid) not in seen and (tid, pid) not in seen:
                add(pid, tid, "link")
    return edges


def hub_and_depth(pid, pages):
    chain = [pid]
    while pages[chain[-1]]["parent"] is not None:
        nxt = pages[chain[-1]]["parent"]
        if nxt in chain:
            fail(f"the parents of '{pid}' loop back on themselves: {' > '.join(chain + [nxt])}.")
        chain.append(nxt)
    if chain[-1] != CENTER:
        fail(f"'{pid}' does not hang from Oak (its top parent is '{chain[-1]}').")
    depth = len(chain) - 1
    hub = chain[-2] if depth >= 1 else None
    return hub, depth


def fetch_active_work(pages):
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        return {}
    work = {}
    url = f"https://api.github.com/repos/{repo}/issues?state=open&per_page=100"
    try:
        while url:
            req = urllib.request.Request(url, headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "oak-wiki-build",
            })
            with urllib.request.urlopen(req, timeout=20) as resp:
                issues = json.load(resp)
                link = resp.headers.get("Link", "")
            for issue in issues:
                if "pull_request" in issue:
                    continue
                for label in issue.get("labels", []):
                    name = label.get("name", "")
                    if name.startswith("wiki:") and name[5:] in pages:
                        work.setdefault(name[5:], []).append({
                            "number": issue["number"],
                            "title": issue["title"],
                            "assignees": [a["login"] for a in issue.get("assignees", [])],
                            "url": issue["html_url"],
                        })
            m = re.search(r'<([^>]+)>;\s*rel="next"', link)
            url = m.group(1) if m else None
    except (urllib.error.URLError, OSError, ValueError) as err:
        print(f"build_graph: could not read issues ({err}); building without active work.", file=sys.stderr)
        return {}
    return work


def main():
    if not WIKI.is_dir():
        fail(f"no wiki folder at {rel(WIKI)}.")
    pages = load_pages()
    edges = collect_edges(pages)
    work = fetch_active_work(pages)

    nodes = []
    for pid, page in pages.items():
        hub, depth = hub_and_depth(pid, pages)
        node = {
            "id": pid,
            "title": page["title"],
            "parent": page["parent"],
            "hub": hub,
            "depth": depth,
            "code": page["code"],
            "path": rel(page["file"]),
            "markdown": page["markdown"],
        }
        if pid in work:
            node["work"] = work[pid]
        nodes.append(node)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"nodes": nodes, "edges": edges}, indent=1), encoding="utf-8")
    links = sum(1 for e in edges if e["kind"] == "link")
    print(f"Wrote {rel(OUT)}: {len(nodes)} pages, {len(edges) - links} parent edges, {links} cross links, "
          f"{sum(len(v) for v in work.values())} active issues.")


if __name__ == "__main__":
    main()
