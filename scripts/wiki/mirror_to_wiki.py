#!/usr/bin/env python3
"""Copy the repo's wiki (README.md + docs/wiki/*.md) into a GitHub wiki clone.

The repo is the source of truth; the GitHub Wiki tab is a read-only mirror.
For each page this script:
  - strips the front matter,
  - rewrites links between wiki pages to GitHub-wiki page names
    (README.md -> Home, docs/wiki/object-detection.md -> Object-detection),
  - rewrites links to other repo files to full GitHub URLs,
  - adds a footer "Edit this page in the repo: <link>".

Every existing .md page in the output folder is deleted first, so pages
removed from the repo disappear from the wiki too.

Usage:
  python3 scripts/wiki/mirror_to_wiki.py --out wiki --repo owner/name [--branch master]
"""
from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_wiki  # noqa: E402  (shared front matter / link parsing)

HOME = "Home"
UNSAFE_NAME_CHARS = re.compile(r"[\\/:*?\"<>|#%]")


def wiki_name(page: check_wiki.Page) -> str:
    """GitHub-wiki page name: the title with spaces as hyphens."""
    if page.slug == check_wiki.CENTER_SLUG:
        return HOME
    title = UNSAFE_NAME_CHARS.sub("", page.title).strip()
    return re.sub(r"\s+", "-", title) or page.slug


def build_name_map(pages: dict) -> dict:
    """repo path -> wiki page name. Pages whose titles clash all use their slug
    instead (slugs are file names, so they are already unique)."""
    real = [p for key, p in pages.items() if key == p.slug]
    wanted = {p.path: wiki_name(p) for p in real}
    counts: dict = {}
    for name in wanted.values():
        counts[name.lower()] = counts.get(name.lower(), 0) + 1
    return {
        p.path: (wanted[p.path] if counts[wanted[p.path].lower()] == 1 or p.slug == check_wiki.CENTER_SLUG
                 else p.slug)
        for p in real
    }


def rewrite_links(body: str, page_path: str, names: dict, repo: str, branch: str) -> str:
    """Rewrite relative links in `body` (from the file at `page_path`)."""
    blob = f"https://github.com/{repo}/blob/{branch}/"
    raw = f"https://github.com/{repo}/raw/{branch}/"

    def fix(match: re.Match) -> str:
        whole, target = match.group(0), match.group(1)
        resolved = check_wiki.resolve_link(page_path, target)
        if resolved is None:
            return whole
        fragment = "#" + target.split("#", 1)[1] if "#" in target else ""
        if resolved in names:
            new = names[resolved] + fragment
        elif whole.startswith("!"):
            new = raw + resolved
        else:
            new = blob + resolved + fragment
        start, end = match.span(1)
        return whole[: start - match.start()] + new + whole[end - match.start():]

    out, in_fence = [], False
    for line in body.splitlines(keepends=True):
        if check_wiki.FENCE_RE.match(line):
            in_fence = not in_fence
        elif not in_fence:
            # Leave inline code alone: rewrite only the parts outside backticks.
            parts = re.split(r"(`[^`]*`)", line)
            line = "".join(p if p.startswith("`") else check_wiki.LINK_RE.sub(fix, p) for p in parts)
        out.append(line)
    return "".join(out)


def render_page(page: check_wiki.Page, names: dict, repo: str, branch: str) -> str:
    body = rewrite_links(page.body, page.path, names, repo, branch).strip("\n")
    edit = f"https://github.com/{repo}/blob/{branch}/{page.path}"
    return f"{body}\n\n---\n\n_Edit this page in the repo: <{edit}>_\n"


def mirror(root: str, out_dir: str, repo: str, branch: str) -> list:
    """Write all pages into out_dir; return the list of file names written."""
    if os.path.isdir(os.path.join(root, check_wiki.WIKI_DIR)):
        pages = check_wiki.load_pages(root)
    else:
        pages = {check_wiki.CENTER_SLUG: check_wiki.read_page(root, check_wiki.CENTER_FILE, check_wiki.CENTER_SLUG)}
    names = build_name_map(pages)
    os.makedirs(out_dir, exist_ok=True)
    for name in os.listdir(out_dir):
        if name.endswith(".md"):
            os.remove(os.path.join(out_dir, name))
    written = []
    for key, page in pages.items():
        if key != page.slug:
            continue
        fname = names[page.path] + ".md"
        with open(os.path.join(out_dir, fname), "w", encoding="utf-8") as f:
            f.write(render_page(page, names, repo, branch))
        written.append(fname)
    return sorted(written)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=".", help="repo root (default: current folder)")
    parser.add_argument("--out", required=True, help="folder of the cloned <repo>.wiki.git")
    parser.add_argument("--repo", required=True, help="GitHub repo as owner/name")
    parser.add_argument("--branch", default="master", help="branch the edit links point at")
    args = parser.parse_args(argv)
    written = mirror(os.path.abspath(args.root), args.out, args.repo, args.branch)
    print(f"Wrote {len(written)} wiki page(s): {', '.join(written)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
