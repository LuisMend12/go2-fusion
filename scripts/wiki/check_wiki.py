#!/usr/bin/env python3
"""Check that the team wiki (README.md + docs/wiki/*.md) is correct.

Runs four checks and explains every problem in plain English:

  1. Pages: every page has a title and a parent that exists, and every
     relative link to a .md file points at a file that exists.
  2. Tree: following parents from any page always reaches README.md
     (the "Oak" page). No orphans, no loops.
  3. Drift: if your branch changed code that a page documents (its `code:`
     globs), that page must change too - unless the pull request body has a
     line "wiki: no change needed - <reason>" (read from env PR_BODY).
  4. Coverage: every top-level folder in src/ is claimed by some page's
     `code:` globs, so a new package always gets a page.

Exit code 0 = all good, 1 = something to fix.
Python 3 standard library only.

Usage:
  python3 scripts/wiki/check_wiki.py                    # compare against origin/master
  python3 scripts/wiki/check_wiki.py --base main        # compare against another ref
  python3 scripts/wiki/check_wiki.py --no-drift         # skip the git comparison
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field

CENTER_FILE = "README.md"
CENTER_SLUG = "oak"
WIKI_DIR = "docs/wiki"
SKIP_LINE_RE = re.compile(r"^\s*wiki:\s*no change needed\s*-\s*\S", re.IGNORECASE | re.MULTILINE)
SKIP_LINE_HINT = "'wiki: no change needed - <reason>'"

# [text](target) or ![alt](target "title"); target may be wrapped in <>.
LINK_RE = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
FENCE_RE = re.compile(r"^\s*(```|~~~)")


# ---------------------------------------------------------------- parsing

@dataclass
class Page:
    slug: str
    path: str  # repo-relative, forward slashes
    meta: dict = field(default_factory=dict)
    body: str = ""
    has_front_matter: bool = False

    @property
    def title(self) -> str:
        return str(self.meta.get("title", "") or "").strip()

    @property
    def parent(self) -> str:
        return str(self.meta.get("parent", "") or "").strip()

    @property
    def code(self) -> list:
        value = self.meta.get("code", [])
        if isinstance(value, str):
            value = [value] if value else []
        return [v for v in value if v]


def _strip_comment(value: str) -> str:
    """Drop a trailing ' # comment' (YAML style) unless it is inside quotes."""
    out, quote = [], None
    for i, ch in enumerate(value):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or value[i - 1].isspace()):
            break
        out.append(ch)
    return "".join(out).strip()


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _parse_value(value: str):
    value = _strip_comment(value)
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        return [_unquote(v) for v in inner.split(",") if v.strip()] if inner else []
    return _unquote(value)


def parse_front_matter(text: str):
    """Return (meta, body, has_front_matter).

    Handles the simple subset the wiki uses: `key: value`, inline lists
    `key: [a, b]`, block lists (`key:` then `  - a` lines) and # comments.
    """
    text = text.lstrip("﻿")
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, text, False
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            end = i
            break
    if end is None:
        return {}, text, False
    meta: dict = {}
    current_list_key = None
    for raw in lines[1:end]:
        line = raw.rstrip("\n").rstrip("\r")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        stripped = line.strip()
        if stripped.startswith("- ") or stripped == "-":
            if current_list_key is not None:
                item = _unquote(_strip_comment(stripped[1:]))
                if item:
                    meta[current_list_key].append(item)
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = _strip_comment(value)
        if value == "":
            meta[key] = []
            current_list_key = key
        else:
            meta[key] = _parse_value(value)
            current_list_key = None
    body = "".join(lines[end + 1:])
    return meta, body, True


def read_page(root: str, rel_path: str, slug: str) -> Page:
    with open(os.path.join(root, rel_path), encoding="utf-8") as f:
        meta, body, has_fm = parse_front_matter(f.read())
    return Page(slug=slug, path=rel_path, meta=meta, body=body, has_front_matter=has_fm)


def load_pages(root: str) -> dict:
    """slug -> Page for README.md (slug 'oak') and every docs/wiki/*.md."""
    pages = {}
    if os.path.isfile(os.path.join(root, CENTER_FILE)):
        center = read_page(root, CENTER_FILE, CENTER_SLUG)
        center.meta.setdefault("title", "Oak")
        pages[CENTER_SLUG] = center
    wiki_abs = os.path.join(root, WIKI_DIR)
    for name in sorted(os.listdir(wiki_abs)):
        if name.endswith(".md") and os.path.isfile(os.path.join(wiki_abs, name)):
            slug = name[:-3]
            if slug == CENTER_SLUG:
                # Reported by check_pages; README.md owns this slug.
                pages["docs/wiki/oak.md"] = read_page(root, f"{WIKI_DIR}/{name}", slug)
                continue
            pages[slug] = read_page(root, f"{WIKI_DIR}/{name}", slug)
    return pages


def iter_links(body: str):
    """Yield link targets outside fenced code blocks and inline code."""
    in_fence = False
    for line in body.splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        line = re.sub(r"`[^`]*`", "", line)
        for m in LINK_RE.finditer(line):
            yield m.group(1)


def is_external(target: str) -> bool:
    return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target)) or target.startswith("//")


def resolve_link(page_path: str, target: str):
    """Repo-relative path a relative link points to, or None if not a file link."""
    if is_external(target) or target.startswith("#"):
        return None
    path = target.split("#", 1)[0].split("?", 1)[0]
    if not path:
        return None
    if path.startswith("/"):
        joined = path.lstrip("/")
    else:
        joined = os.path.join(os.path.dirname(page_path), path)
    return os.path.normpath(joined).replace(os.sep, "/")


# ---------------------------------------------------------------- globs

def glob_to_regex(pattern: str) -> re.Pattern:
    """Translate a path glob: ** = any folders, * = anything but '/', ? = one char.

    A pattern with no wildcard also matches everything inside it when it is a
    folder, so `src/foo` and `src/foo/` behave like `src/foo/**`.
    """
    pattern = pattern.strip()
    if pattern.startswith("./"):
        pattern = pattern[2:]
    pattern = pattern.lstrip("/")
    if not any(c in pattern for c in "*?["):
        base = re.escape(pattern.rstrip("/"))
        return re.compile(rf"^{base}(/.*)?$")
    i, out = 0, []
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def matches_any(path: str, patterns) -> bool:
    return any(glob_to_regex(p).match(path) for p in patterns)


# ---------------------------------------------------------------- checks

def check_pages(root: str, pages: dict) -> list:
    problems = []
    for key, page in pages.items():
        if key != page.slug:  # docs/wiki/oak.md
            problems.append(
                f"{page.path} uses the name 'oak', which is reserved for the center page "
                f"(README.md). Rename the file."
            )
            continue
        if page.slug != CENTER_SLUG:
            if not page.has_front_matter:
                problems.append(
                    f"{page.path} has no front matter. Start the file with a '---' block "
                    f"holding at least 'title:' and 'parent:'."
                )
                continue
            if not page.title:
                problems.append(f"{page.path} has no title. Add a 'title:' line to its front matter.")
            if not page.parent:
                problems.append(
                    f"{page.path} has no parent. Add a 'parent:' line naming the page it hangs "
                    f"under (hub pages use 'parent: oak')."
                )
            elif page.parent not in pages or pages[page.parent].slug != page.parent:
                problems.append(
                    f"{page.path} says its parent is '{page.parent}', but there is no page "
                    f"{WIKI_DIR}/{page.parent}.md. Fix the name or create that page."
                )
        for target in iter_links(page.body):
            resolved = resolve_link(page.path, target)
            if resolved is None or not resolved.endswith(".md"):
                continue
            if not os.path.isfile(os.path.join(root, resolved)):
                problems.append(
                    f"{page.path} links to '{target}', but {resolved} does not exist. "
                    f"Fix the link or create the page."
                )
    return problems


def check_tree(pages: dict) -> list:
    problems = []
    for key, page in pages.items():
        if key != page.slug or page.slug == CENTER_SLUG:
            continue
        chain, current = [page.slug], page
        while True:
            parent = current.parent
            if not parent or parent not in pages or pages[parent].slug != parent:
                break  # already reported by check_pages
            if parent == CENTER_SLUG:
                break
            if parent in chain:
                chain.append(parent)
                problems.append(
                    f"{page.path} never reaches the Oak page (README.md): its parents go in a "
                    f"circle ({' -> '.join(chain)}). Point one of them at a hub or at 'oak'."
                )
                break
            chain.append(parent)
            current = pages[parent]
    return problems


def check_coverage(root: str, pages: dict) -> list:
    src = os.path.join(root, "src")
    if not os.path.isdir(src):
        return []
    globs = [g for p in pages.values() for g in p.code]
    problems = []
    for name in sorted(os.listdir(src)):
        folder = os.path.join(src, name)
        if name.startswith(".") or not os.path.isdir(folder):
            continue
        rel_dir = f"src/{name}"
        if _folder_claimed(root, rel_dir, globs):
            continue
        problems.append(
            f"{rel_dir} has no wiki page. Create {WIKI_DIR}/<name>.md for it with "
            f"'code: [{rel_dir}/**]' in its front matter, and link it from its hub page."
        )
    return problems


def _folder_claimed(root: str, rel_dir: str, globs) -> bool:
    if matches_any(rel_dir, globs) or matches_any(rel_dir + "/", globs):
        return True
    for dirpath, dirnames, filenames in os.walk(os.path.join(root, rel_dir)):
        dirnames[:] = [d for d in dirnames if d not in (".git", "__pycache__")]
        for fname in filenames:
            rel = os.path.relpath(os.path.join(dirpath, fname), root).replace(os.sep, "/")
            if matches_any(rel, globs):
                return True
    return False


def _git(root: str, *args) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def changed_files(root: str, base: str) -> list:
    """Files that differ between the merge base with `base` and the working tree
    (committed, staged, unstaged and new untracked files)."""
    merge_base = _git(root, "merge-base", base, "HEAD").strip()
    files = set(_git(root, "diff", "--name-only", merge_base).split("\n"))
    files |= set(_git(root, "ls-files", "--others", "--exclude-standard").split("\n"))
    return sorted(f for f in files if f)


def check_drift(pages: dict, changed: list, pr_body: str) -> list:
    if SKIP_LINE_RE.search(pr_body or ""):
        return []
    changed_set = set(changed)
    problems = []
    for key, page in pages.items():
        if key != page.slug or not page.code:
            continue
        hits = [f for f in changed if matches_any(f, page.code)]
        if not hits or page.path in changed_set:
            continue
        shown = ", ".join(hits[:3]) + (f" and {len(hits) - 3} more" if len(hits) > 3 else "")
        problems.append(
            f"You changed {shown}, but its wiki page {page.path} did not change. "
            f"Update the page, or add {SKIP_LINE_HINT} to your pull request."
        )
    return problems


# ---------------------------------------------------------------- main

def run(root: str, base, pr_body: str, out=sys.stdout) -> int:
    def say(msg=""):
        print(msg, file=out)

    if not os.path.isdir(os.path.join(root, WIKI_DIR)):
        say(f"Note: {WIKI_DIR}/ does not exist yet, so there is no wiki to check. Passing.")
        return 0

    pages = load_pages(root)
    sections = [
        ("Pages and links", check_pages(root, pages)),
        ("Every page connects to Oak", check_tree(pages)),
    ]
    if base:
        try:
            changed = changed_files(root, base)
        except RuntimeError as err:
            say(f"Could not compare your branch with '{base}': {err}")
            say("Run 'git fetch origin' and try again, or pass --base <branch>.")
            return 1
        sections.append(("Wiki kept up to date with code changes", check_drift(pages, changed, pr_body)))
    sections.append(("Every package in src/ has a page", check_coverage(root, pages)))

    total = sum(len(p) for _, p in sections)
    real_pages = sum(1 for k, p in pages.items() if k == p.slug)
    for title, problems in sections:
        mark = "ok" if not problems else f"{len(problems)} problem(s)"
        say(f"[{mark}] {title}")
        for p in problems:
            say(f"  - {p}")
    say()
    if total:
        say(f"Wiki check failed: {total} thing(s) to fix across {real_pages} page(s).")
        return 1
    note = "" if base else " (code-change check skipped)"
    say(f"Wiki check passed: {real_pages} page(s) look good{note}.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", help="repo root (default: the git top-level folder)")
    parser.add_argument("--base", default="origin/master", help="branch to compare against (default: origin/master)")
    parser.add_argument("--no-drift", action="store_true", help="skip the code-change check")
    args = parser.parse_args(argv)
    root = args.root
    if not root:
        try:
            root = _git(os.getcwd(), "rev-parse", "--show-toplevel").strip()
        except RuntimeError:
            root = os.getcwd()
    base = None if args.no_drift else args.base
    return run(os.path.abspath(root), base, os.environ.get("PR_BODY", ""))


if __name__ == "__main__":
    sys.exit(main())
