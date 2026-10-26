#!/usr/bin/env python3
"""Post to Discord when someone asks a wiki question or asks for review.

Run by .github/workflows/discord-ping.yml after build_graph.py, so it can read
site/graph.json (team, pages, open work, last changes).

    DISCORD_REVIEW_WEBHOOK_URL=...  GITHUB_EVENT_NAME=pull_request_target \
        GITHUB_EVENT_PATH=event.json  python3 scripts/wiki/discord_ping.py

Fires on:
- a pull request that asks for review (opened ready for review,
  ready_for_review, review_requested): posts Who, What, Why, Before, After,
  the wiki pages it touches and the link, read from the pull request
  template (.github/pull_request_template.md), to #feature-revisions;
- an issue labelled "question" (opened with the label, or labelled later):
  posts the question and mentions the page owners.

Where it posts (repo secrets):
- reviews:   DISCORD_REVIEW_WEBHOOK_URL, else DISCORD_WEBHOOK_URL
- questions: DISCORD_QUESTIONS_WEBHOOK_URL, else DISCORD_REVIEW_WEBHOOK_URL,
             else DISCORD_WEBHOOK_URL
None set: prints "Discord not set up yet" and exits 0.

A person is @mentioned when their discord_id is filled in docs/team.yml,
otherwise named. Standard library only.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GRAPH = ROOT / "site" / "graph.json"
# GitHub sends "opened" and then "labeled" for labels set at creation, and
# "opened" then "review_requested" for reviewers set at creation. A second
# event this soon after creation is that echo, so it is skipped.
ECHO_SECONDS = 60
WEBHOOKS = {
    "review": ["DISCORD_REVIEW_WEBHOOK_URL", "DISCORD_WEBHOOK_URL"],
    "question": ["DISCORD_QUESTIONS_WEBHOOK_URL", "DISCORD_REVIEW_WEBHOOK_URL", "DISCORD_WEBHOOK_URL"],
}
NOT_FILLED = "not filled in"

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


def page_link(graph, slug, embed=False):
    repo = graph.get("repo", "maxhawksby/go2-fusion")
    node = next((n for n in graph.get("nodes", []) if n["id"] == slug), None)
    title = node["title"] if node else slug
    path = node["path"] if node else f"docs/wiki/{slug}.md"
    branch = graph.get("branch") or "master"
    url = f"https://github.com/{repo}/blob/{branch}/{path}"
    # In plain messages <url> stops Discord from adding a preview card;
    # embeds do not need it (and do not render it).
    return f"[{title}]({url})" if embed else f"[{title}](<{url}>)"


def asker_text(graph, login):
    return mention(person_by(graph, login=login), login or "someone")


# ------------------------------------------------- pull request template

SECTION_NAMES = ("who", "what", "why", "before", "after", "how to test", "wiki")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_NAMES = "|".join(SECTION_NAMES)
# A section starts at "## Why" (heading alone on its line), "**Why**" or
# "**Why:**" (bold label, text may follow) or "Why:" (label, text may follow).
_HEADING_RE = re.compile(
    rf"^\s*(?:#{{1,6}}\s*({_NAMES})\s*:?\s*$"
    rf"|(?:\*\*|__)({_NAMES})\s*:?\s*(?:\*\*|__)\s*:?\s*(.*)$"
    rf"|({_NAMES})\s*:\s*(.*)$)",
    re.IGNORECASE)
_LABEL_ONLY_RE = re.compile(r"^\s*(?:#{1,6}\s*\S|<details|</details|<summary)", re.IGNORECASE)
# The /pr skill's bullet: "- Before: <old>. After: <new>."
# The labels need their colon, so "after one frame" in the text is not one.
_BEFORE_AFTER_RE = re.compile(
    r"^\s*[-*]\s*(?:\*\*)?Before(?::\*\*|\*\*:|:)\s*(.+?)\s+(?:\*\*)?After(?::\*\*|\*\*:|:)\s*(.+?)\s*$",
    re.IGNORECASE)


def _clean(text):
    lines = [ln.rstrip() for ln in text.strip().splitlines()]
    return "\n".join(lines).strip()


def _is_heading(line):
    """(section, text on the same line) when the line starts a section."""
    m = _HEADING_RE.match(line)
    if not m:
        return None
    name = m.group(1) or m.group(2) or m.group(4)
    rest = m.group(3) if m.group(2) else m.group(5) if m.group(4) else ""
    return name.lower(), (rest or "").strip()


def parse_template(body):
    """Read the pull request body into {section: text}.

    Knows the template's sections (Who, What, Why, Before, After, How to
    test, Wiki) as markdown headings, bold labels or "Name:" lines. Template
    prompts are HTML comments, so an untouched template parses as empty.
    For the /pr format it also reads "- Before: ... After: ..." bullets and
    the opening paragraph. Missing sections are simply absent.
    """
    text = _COMMENT_RE.sub("", body or "").replace("\r\n", "\n")
    sections, current, buf = {}, None, []

    def flush():
        if current and current not in sections:
            value = _clean("\n".join(buf))
            if value:
                sections[current] = value

    for line in text.split("\n"):
        head = _is_heading(line)
        if head:
            flush()
            current, buf = head[0], [head[1]] if head[1] else []
        elif _LABEL_ONLY_RE.match(line):
            flush()
            current, buf = None, []
        elif current:
            buf.append(line)
    flush()

    before, after = [], []
    for line in text.split("\n"):
        m = _BEFORE_AFTER_RE.match(line)
        if m:
            before.append(m.group(1).rstrip("."))
            after.append(m.group(2).rstrip("."))
    if before:
        sections.setdefault("before", "\n".join(f"- {b}." if len(before) > 1 else f"{b}." for b in before))
        sections.setdefault("after", "\n".join(f"- {a}." if len(after) > 1 else f"{a}." for a in after))

    first = first_paragraph(text)
    if first:
        sections["_first"] = first
    return sections


def first_paragraph(text):
    """The first plain paragraph: no heading, label, bullet or fold."""
    for block in re.split(r"\n\s*\n", _COMMENT_RE.sub("", text or "")):
        block = block.strip()
        if not block or _LABEL_ONLY_RE.match(block) or _is_heading(block.split("\n")[0]):
            continue
        if re.match(r"^\s*([-*+]|\d+\.)\s", block) or block.lower().startswith("wiki:"):
            continue
        return " ".join(ln.strip() for ln in block.splitlines())
    return ""


def _short(text, limit=900):
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _color(person):
    try:
        return int((person or {}).get("color", "").lstrip("#"), 16)
    except ValueError:
        return None


# ---------------------------------------------------------------- events

def _question(event, graph):
    action = event.get("action")
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
    return {"content": "\n".join(lines)}


def _review_targets(event):
    """Reviewer logins to mention, or None when this event should not post.

    One post per review request:
    - "opened" posts unless the pull request is a draft;
    - "ready_for_review" posts;
    - "review_requested" is skipped on drafts and right after creation (the
      "opened" post covers it). Asking for several reviewers at once fires
      one event per reviewer; only the event for the last of them posts.
    """
    action = event.get("action")
    pr = event.get("pull_request") or {}
    current = [r.get("login") for r in pr.get("requested_reviewers") or [] if r.get("login")]
    if action == "opened":
        return None if pr.get("draft") else current
    if action == "ready_for_review":
        return current
    if action != "review_requested" or pr.get("draft"):
        return None
    made, now = _when(pr.get("created_at")), _when(pr.get("updated_at"))
    if made and now and (now - made).total_seconds() < ECHO_SECONDS:
        return None
    login = (event.get("requested_reviewer") or {}).get("login")
    if login and current and current[-1] != login and login in current:
        return None  # a later event in this batch posts for everyone
    return current or ([login] if login else [])


def _review(event, graph):
    reviewers = _review_targets(event)
    if reviewers is None:
        return None
    pr = event.get("pull_request") or {}
    url = pr.get("html_url", "")
    author = (pr.get("user") or {}).get("login", "")
    person = person_by(graph, login=author)
    work = next((w for w in graph.get("work", []) if w.get("kind") == "pr"
                 and w.get("number") == pr.get("number")), None)
    pages = (work or {}).get("pages") or _pages_from_labels(pr, graph)
    sec = parse_template(pr.get("body"))

    who = (f"{person.get('name')} (@{author})" if person else f"@{author}" if author else "someone")
    if sec.get("who"):
        who += "\n" + sec["who"]
    what = f"**{pr.get('title', '')}**" + (f"\n{sec['what']}" if sec.get("what") else "")
    why = sec.get("why") or sec.get("_first") or NOT_FILLED
    if pages:
        wiki = ", ".join(page_link(graph, p, embed=True) for p in pages[:8])
    else:
        wiki = sec.get("wiki") or "none listed"

    fields = [
        {"name": "Who", "value": _short(who), "inline": False},
        {"name": "What", "value": _short(what), "inline": False},
        {"name": "Why", "value": _short(why), "inline": False},
        {"name": "Before", "value": _short(sec.get("before") or NOT_FILLED), "inline": False},
        {"name": "After", "value": _short(sec.get("after") or NOT_FILLED), "inline": False},
        {"name": "Wiki pages", "value": _short(wiki), "inline": False},
        {"name": "Review it", "value": url or "no link", "inline": False},
    ]
    embed = {"title": _short(f"Review: {pr.get('title', '')}", 250), "url": url, "fields": fields}
    if not sec.get("why"):
        embed["footer"] = {"text": "Why not filled in - showing the description's first paragraph."
                           if sec.get("_first") else "Template not filled in."}
    color = _color(person)
    if color is not None:
        embed["color"] = color

    # Reviews go to the whole team, never one person: anyone can pick it up.
    asker = (person or {}).get("name") or (f"@{author}" if author else "someone")
    head = f"**Review requested by {asker}** - any teammate can review"
    return {"content": f"{head}: <{url}>", "embeds": [embed]}


def build_message(event_name, event, graph):
    """Return (kind, Discord payload) or None if this event needs no post.

    kind is "question" or "review"; it picks the webhook.
    """
    if event_name == "issues":
        payload = _question(event, graph)
        return ("question", payload) if payload else None
    if event_name in ("pull_request", "pull_request_target"):
        payload = _review(event, graph)
        return ("review", payload) if payload else None
    return None


def as_text(payload):
    """Plain-text view of a payload, for the workflow log."""
    out = [payload.get("content", "")]
    for embed in payload.get("embeds", []):
        out.append(embed.get("title", ""))
        out += [f"{f['name']}: {f['value']}" for f in embed.get("fields", [])]
        if embed.get("footer"):
            out.append(embed["footer"]["text"])
    return "\n".join(out)


def webhook_for(kind, env=None):
    env = os.environ if env is None else env
    for name in WEBHOOKS[kind]:
        value = (env.get(name) or "").strip()
        if value:
            return name, value
    return None, ""


def fresh_reviewers(event):
    """Re-read the pull request's reviewers from GitHub.

    "gh pr create --reviewer" adds reviewers a moment after "opened" fires,
    so the event can list none. Uses GITHUB_TOKEN; keeps the event's list on
    any failure.
    """
    pr = event.get("pull_request") or {}
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    api = pr.get("url")
    if not (token and api):
        return
    req = urllib.request.Request(api, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "User-Agent": "oak-wiki-discord-ping"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            live = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return
    if isinstance(live.get("requested_reviewers"), list):
        pr["requested_reviewers"] = live["requested_reviewers"]
    if live.get("body") is not None:
        pr["body"] = live["body"]


def post(webhook, payload):
    body = dict(payload)
    body["content"] = body.get("content", "")[:1990]
    body["allowed_mentions"] = {"parse": ["users"]}
    req = urllib.request.Request(webhook, data=json.dumps(body).encode(), method="POST", headers={
        "Content-Type": "application/json",
        "User-Agent": "oak-wiki-discord-ping (https://github.com/maxhawksby/go2-fusion, 1)",
    })
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.status


def main():
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    path = os.environ.get("GITHUB_EVENT_PATH", "")
    event = json.loads(Path(path).read_text(encoding="utf-8")) if path and Path(path).exists() else {}
    kind = "question" if event_name == "issues" else "review"
    name, webhook = webhook_for(kind)
    if not webhook:
        print(f"Discord not set up yet (no {' / '.join(WEBHOOKS[kind])} secret); skipping.")
        return 0
    if event_name.startswith("pull_request") and event.get("action") == "opened":
        fresh_reviewers(event)
    graph = json.loads(GRAPH.read_text(encoding="utf-8")) if GRAPH.exists() else {}
    message = build_message(event_name, event, graph)
    if not message:
        print(f"No ping for {event_name}/{event.get('action')}.")
        return 0
    kind, payload = message
    try:
        post(webhook, payload)
    except (urllib.error.URLError, OSError) as err:
        print(f"discord_ping: could not post to Discord ({err}).", file=sys.stderr)
        return 1
    print(f"Posted to Discord ({name}):\n" + as_text(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
