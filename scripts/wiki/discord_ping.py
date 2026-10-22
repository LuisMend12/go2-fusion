#!/usr/bin/env python3
"""Post a Discord message when someone asks a wiki question or asks for review.

Run by .github/workflows/discord-ping.yml after build_graph.py, so it can read
site/graph.json (team, pages, open work, last changes).

    DISCORD_WEBHOOK_URL=...  GITHUB_EVENT_NAME=issues  GITHUB_EVENT_PATH=event.json \
        python3 scripts/wiki/discord_ping.py

Fires on:
- an issue labelled "question" (opened with the label, or labelled later);
- a pull request that asks for review (review_requested, ready_for_review).

It mentions the page owners: people whose open work touches the page, else
the person who last changed it. A person is @mentioned when their
discord_id is filled in docs/team.yml, otherwise named.

No DISCORD_WEBHOOK_URL: prints "Discord not set up yet" and exits 0.
Standard library only.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GRAPH = ROOT / "site" / "graph.json"
# GitHub sends "opened" and then "labeled" for labels set at creation. A
# "labeled" event this soon after creation is that echo, so it is skipped.
ECHO_SECONDS = 60


def _when(text):
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None


def _labels(item):
    return [lb.get("name", "") for lb in item.get("labels", [])]


def _pages_from_labels(item, graph):
    known = {n["id"] for n in graph.get("nodes", [])}
    return [n[5:] for n in _labels(item) if n.startswith("wiki:") and n[5:] in known]


def person_by(graph, pid=None, login=None):
    for p in graph.get("people", []):
        if pid and p.get("id") == pid:
            return p
        if login and p.get("github", "").lower() == login.lower():
            return p
    return None


def mention(person, fallback=""):
    if person and person.get("discord_id"):
        return f"<@{person['discord_id']}>"
    if person:
        return person.get("name") or person.get("id")
    return fallback


def owners(graph, pages, exclude=()):
    """Team ids who own these pages: open work on them, else the last changer."""
    out = []
    for w in graph.get("work", []):
        if set(w.get("pages", [])) & set(pages):
            for pid in [w.get("person")] + list(w.get("assignees", [])):
                if pid and pid not in out:
                    out.append(pid)
    out = [p for p in out if p not in exclude]
    if out:
        return out
    nodes = {n["id"]: n for n in graph.get("nodes", [])}
    for page in pages:
        last = (nodes.get(page) or {}).get("last_change") or {}
        pid = last.get("person")
        if pid and pid not in out and pid not in exclude:
            out.append(pid)
    return out


def page_link(graph, slug):
    repo = graph.get("repo", "maxhawksby/go2-fusion")
    node = next((n for n in graph.get("nodes", []) if n["id"] == slug), None)
    title = node["title"] if node else slug
    path = node["path"] if node else f"docs/wiki/{slug}.md"
    branch = graph.get("branch") or "master"
    return f"[{title}](<https://github.com/{repo}/blob/{branch}/{path}>)"


def asker_text(graph, login):
    return mention(person_by(graph, login=login), login or "someone")


def build_message(event_name, event, graph):
    """Return the Discord message text, or None if this event needs no ping."""
    action = event.get("action")
    if event_name == "issues":
        issue = event.get("issue") or {}
        if "question" not in _labels(issue):
            return None
        if action == "labeled":
            if (event.get("label") or {}).get("name") != "question":
                return None
            made, now = _when(issue.get("created_at")), _when(issue.get("updated_at"))
            if made and now and (now - made).total_seconds() < ECHO_SECONDS:
                return None  # the "opened" event already pinged
        elif action != "opened":
            return None
        asker = (issue.get("user") or {}).get("login", "")
        pages = _pages_from_labels(issue, graph)
        who = owners(graph, pages, exclude={(person_by(graph, login=asker) or {}).get("id")})
        lines = [f"**Question** from {asker_text(graph, asker)}"
                 + (f" on {', '.join(page_link(graph, p) for p in pages)}" if pages else "")
                 + f": {issue.get('title', '')}",
                 f"<{issue.get('html_url', '')}>"]
        if who:
            lines.append("Can you help? " + " ".join(mention(person_by(graph, pid=p)) for p in who))
        return "\n".join(lines)

    if event_name in ("pull_request", "pull_request_target"):
        pr = event.get("pull_request") or {}
        if action == "review_requested":
            reviewer = event.get("requested_reviewer") or {}
            # A team review request has no single login; page owners get pinged.
            reviewers = [reviewer.get("login")] if reviewer.get("login") else []
        elif action == "ready_for_review":
            reviewers = [r.get("login") for r in pr.get("requested_reviewers") or [] if r.get("login")]
        else:
            return None
        author = (pr.get("user") or {}).get("login", "")
        work = next((w for w in graph.get("work", []) if w.get("kind") == "pr"
                     and w.get("number") == pr.get("number")), None)
        pages = (work or {}).get("pages") or _pages_from_labels(pr, graph)
        author_id = (person_by(graph, login=author) or {}).get("id")
        named = [mention(person_by(graph, login=r), r) for r in reviewers]
        reviewer_ids = {(person_by(graph, login=r) or {}).get("id") for r in reviewers}
        extra = [mention(person_by(graph, pid=p)) for p in owners(graph, pages, exclude={author_id} | reviewer_ids)]
        lines = [f"**Review requested** by {asker_text(graph, author)}"
                 + (f" on {', '.join(page_link(graph, p) for p in pages[:5])}" if pages else "")
                 + f": {pr.get('title', '')}",
                 f"<{pr.get('html_url', '')}>"]
        if named:
            lines.append("Reviewer: " + " ".join(named))
        if extra:
            lines.append("Page owners: " + " ".join(extra))
        return "\n".join(lines)
    return None


def post(webhook, text):
    body = json.dumps({"content": text[:1990], "allowed_mentions": {"parse": ["users"]}}).encode()
    req = urllib.request.Request(webhook, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "User-Agent": "oak-wiki-discord-ping (https://github.com/maxhawksby/go2-fusion, 1)",
    })
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.status


def main():
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        print("Discord not set up yet (no DISCORD_WEBHOOK_URL secret); skipping.")
        return 0
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    graph = json.loads(GRAPH.read_text(encoding="utf-8")) if GRAPH.exists() else {}
    text = build_message(event_name, event, graph)
    if not text:
        print(f"No ping for {event_name}/{event.get('action')}.")
        return 0
    try:
        post(webhook, text)
    except (urllib.error.URLError, OSError) as err:
        print(f"discord_ping: could not post to Discord ({err}).", file=sys.stderr)
        return 1
    print("Posted to Discord:\n" + text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
