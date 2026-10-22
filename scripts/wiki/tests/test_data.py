"""Tests for build_graph.py (graph.json v2 data) and discord_ping.py.

Run from the repo root:  python3 -m unittest discover -s scripts/wiki/tests -v

Pure functions only, with fixtures: no network, no git.
"""
from __future__ import annotations

import math
import os
import sys
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import build_graph as bg  # noqa: E402
import discord_ping as dp  # noqa: E402

TEAM_YML = """\
# comment line
people:
  - id: max
    name: Max
    github: maxhawksby
    color: "#ff4d5e"   # red
    discord_id: ""
    focus: Computer vision - YOLO
    past: [object-detection]

  - id: luis
    name: Luis
    github: LuisMend12
    color: "#b5e61d"
    discord_id: "123456789"
    focus: Auto mapper
"""
PEOPLE = bg.parse_team(TEAM_YML)


def tree():
    """Oak, 3 hubs, 7 pages under them, one page two levels down."""
    spec = {"oak": None, "senses": "oak", "driving": "oak", "brains": "oak",
            "lidar": "senses", "camera": "senses", "tf": "senses", "slam": "senses",
            "gamepad": "driving", "voice": "brains", "llm-agent": "brains", "deep": "llm-agent"}
    depth = {}

    def d(pid):
        return 0 if spec[pid] is None else 1 + d(spec[pid])

    nodes = []
    for pid in sorted(spec, reverse=True):  # deliberately unsorted input
        depth[pid] = d(pid)
        nodes.append({"id": pid, "parent": spec[pid], "depth": depth[pid]})
    return nodes


class TestLayout(unittest.TestCase):
    def test_same_input_same_positions(self):
        a = bg.layout(tree())
        b = bg.layout(list(reversed(tree())))
        self.assertEqual(a, b)

    def test_oak_center_hubs_on_ring_no_overlap(self):
        pos = bg.layout(tree())
        self.assertEqual(pos["oak"], (0.0, 0.0))
        for hub in ("senses", "driving", "brains"):
            self.assertAlmostEqual(math.hypot(*pos[hub]), 320.0, delta=0.2)
        ids = sorted(pos)
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                dist = math.hypot(pos[a][0] - pos[b][0], pos[a][1] - pos[b][1])
                self.assertGreaterEqual(dist, 50, f"{a} and {b} overlap")

    def test_pages_sit_closer_to_their_hub_than_to_other_hubs(self):
        pos = bg.layout(tree())

        def dist(a, b):
            return math.hypot(pos[a][0] - pos[b][0], pos[a][1] - pos[b][1])

        for page, hub in (("lidar", "senses"), ("gamepad", "driving"), ("voice", "brains")):
            others = [h for h in ("senses", "driving", "brains") if h != hub]
            self.assertTrue(all(dist(page, hub) < dist(page, o) for o in others), page)


class TestGlobs(unittest.TestCase):
    PAGES = {
        "slam": {"file": bg.WIKI / "slam.md", "code": ["src/go2_robot_sdk/config/mapper_params_online_async.yaml"]},
        "auto-mapper": {"file": bg.WIKI / "auto-mapper.md", "code": ["src/go2_auto_mapper/**"]},
        "lidar": {"file": bg.WIKI / "lidar.md", "code": ["src/lidar_processor*/**"]},
        "oak": {"file": bg.ROOT / "README.md", "code": []},
    }

    def test_code_globs_and_page_files(self):
        hit = bg.pages_for_files([
            "src/go2_auto_mapper/go2_auto_mapper/explorer.py",
            "src/lidar_processor_cpp/src/main.cpp",
            "docs/wiki/slam.md",
        ], self.PAGES)
        self.assertEqual(hit, ["auto-mapper", "lidar", "slam"])

    def test_readme_maps_to_oak_and_unrelated_files_to_nothing(self):
        self.assertEqual(bg.pages_for_files(["README.md"], self.PAGES), ["oak"])
        self.assertEqual(bg.pages_for_files(["docker/Dockerfile", "src/go2_robot_sdk/x.py"], self.PAGES), [])

    def test_star_does_not_cross_folders(self):
        self.assertTrue(bg.matches("src/a/b.py", ["src/a/*.py"]))
        self.assertFalse(bg.matches("src/a/c/b.py", ["src/a/*.py"]))


class TestPeople(unittest.TestCase):
    def test_parse_team(self):
        self.assertEqual([p["id"] for p in PEOPLE], ["max", "luis"])
        self.assertEqual(PEOPLE[0]["color"], "#ff4d5e")
        self.assertEqual(PEOPLE[0]["focus"], "Computer vision - YOLO")
        self.assertEqual(PEOPLE[1]["discord_id"], "123456789")
        self.assertEqual(PEOPLE[0]["past"], ["object-detection"])
        self.assertEqual(PEOPLE[1]["past"], [])

    def test_contributions_by_commit_count(self):
        pages = {
            "oak": {"file": bg.ROOT / "README.md", "code": []},
            "slam": {"file": bg.WIKI / "slam.md", "code": ["src/slam/**"]},
            "lidar": {"file": bg.WIKI / "lidar.md", "code": ["src/lidar/**"]},
            "voice": {"file": bg.WIKI / "voice.md", "code": ["src/voice/**"]},
        }

        def c(name, email, *files):
            return {"author": name, "email": email, "files": list(files)}
        luis = "128239393+LuisMend12@users.noreply.github.com"
        commits = [
            c("LuisM23", luis, "src/lidar/a.py", "README.md"),
            c("LuisMend12", luis, "src/lidar/b.py"),
            c("LuisMend12", luis, "docs/wiki/slam.md"),        # wiki edit: not code work
            c("LuisMend12", luis, "slam/old_layout.py"),        # pre-src/ layout still counts
            c("Max Hawksby", "max@example.com", "docs/wiki/voice.md", "src/voice/x.py"),
            c("Stranger", "s@example.com", "src/slam/x.py"),
        ]
        got = bg.contributions(commits, pages, PEOPLE)
        self.assertEqual(got["luis"], ["lidar", "slam"])  # 2 commits, then 1; Oak left out
        self.assertEqual(got["max"], ["voice"])            # one commit, counted once
        self.assertEqual(bg.contributions(commits, pages, PEOPLE, limit=1)["luis"], ["lidar"])
        bulk = [c("LuisMend12", luis, *[f"src/voice/{i}.py" for i in range(bg.BULK_COMMIT_FILES + 1)])]
        self.assertEqual(bg.contributions(bulk, pages, PEOPLE)["luis"], [])  # a repo-wide move says nothing

    def test_match_by_login_email_and_name(self):
        m = bg.match_person
        self.assertEqual(m(PEOPLE, login="luismend12"), "luis")
        self.assertEqual(m(PEOPLE, name="LuisM23", email="128239393+LuisMend12@users.noreply.github.com"), "luis")
        self.assertEqual(m(PEOPLE, name="Max Hawksby", email="someone@example.com"), "max")
        self.assertEqual(m(PEOPLE, name="maxhawksby"), "max")
        self.assertIsNone(m(PEOPLE, name="Stranger", email="x@example.com"))
        self.assertIsNone(m(PEOPLE, login="dependabot[bot]"))


PAGES = {"slam": {}, "voice": {}}


def issue(labels, user="newbie", comments=0, **extra):
    return {"number": 7, "title": "How does SLAM localize?", "html_url": "https://github.com/x/y/issues/7",
            "user": {"login": user}, "labels": [{"name": n} for n in labels], "comments": comments,
            "updated_at": "2026-10-20T10:00:00Z", "created_at": "2026-10-20T09:00:00Z", **extra}


class TestQuestions(unittest.TestCase):
    def test_unanswered_when_only_asker_or_bots_commented(self):
        q = bg.question_from_issue(issue(["question", "wiki:slam"]), [
            {"user": {"login": "newbie"}, "body": "bump"},
            {"user": {"login": "github-actions[bot]"}, "body": "noted"},
        ], PAGES)
        self.assertEqual(q["page"], "slam")
        self.assertFalse(q["answered"])
        self.assertEqual(q["answer_excerpt"], "")

    def test_answered_by_someone_else(self):
        q = bg.question_from_issue(issue(["question", "wiki:slam"]), [
            {"user": {"login": "LuisMend12"}, "body": "It turns 360 degrees\nfirst."},
        ], PAGES)
        self.assertTrue(q["answered"])
        self.assertEqual(q["answer_excerpt"], "It turns 360 degrees first.")

    def test_answered_label(self):
        q = bg.question_from_issue(issue(["question", "wiki:slam", "answered"]), [], PAGES)
        self.assertTrue(q["answered"])

    def test_not_a_question_or_no_page(self):
        self.assertIsNone(bg.question_from_issue(issue(["wiki:slam"]), [], PAGES))
        self.assertIsNone(bg.question_from_issue(issue(["question"]), [], PAGES))
        self.assertIsNone(bg.question_from_issue(issue(["question", "wiki:nope"]), [], PAGES))

    def test_questions_are_not_work_but_wiki_issues_are(self):
        self.assertIsNone(bg.work_from_issue(issue(["question", "wiki:slam"]), PAGES, PEOPLE))
        w = bg.work_from_issue(issue(["wiki:slam"], user="LuisMend12", assignees=[{"login": "maxhawksby"}]),
                               PAGES, PEOPLE)
        self.assertEqual((w["kind"], w["person"], w["assignees"], w["pages"]), ("issue", "luis", ["max"], ["slam"]))

    def test_pr_review_requested(self):
        pages = {"slam": {"file": bg.WIKI / "slam.md", "code": ["src/slam/**"]}}
        pr = {"number": 3, "user": {"login": "maxhawksby"}, "labels": [], "requested_reviewers": [],
              "draft": True, "updated_at": "", "title": "t", "html_url": "u"}
        w = bg.work_from_pr(pr, ["src/slam/a.py"], pages, PEOPLE)
        self.assertEqual((w["pages"], w["review_requested"], w["draft"], w["person"]), (["slam"], False, True, "max"))
        pr["requested_reviewers"] = [{"login": "LuisMend12"}]
        self.assertTrue(bg.work_from_pr(pr, [], pages, PEOPLE)["review_requested"])
        pr["requested_reviewers"], pr["labels"] = [], [{"name": "review"}]
        self.assertTrue(bg.work_from_pr(pr, [], pages, PEOPLE)["review_requested"])


class TestSummary(unittest.TestCase):
    def test_first_sentence_plain_text(self):
        md = "# SLAM\n\nPart of: [Maps](maps.md)\n\n`slam_toolbox` builds a **2D map** from [/scan](x.md). More.\n"
        self.assertEqual(bg.summarize(md), "slam_toolbox builds a 2D map from /scan.")

    def test_short_first_sentence_takes_the_next(self):
        self.assertEqual(bg.summarize("Welcome! Oak is a dog. It walks."), "Welcome! Oak is a dog.")


GRAPH = {
    "repo": "maxhawksby/go2-fusion", "branch": "master",
    "people": PEOPLE,
    "nodes": [
        {"id": "slam", "title": "SLAM", "path": "docs/wiki/slam.md",
         "last_change": {"person": "max"}},
        {"id": "voice", "title": "Voice", "path": "docs/wiki/voice.md", "last_change": {"person": "max"}},
    ],
    "work": [{"kind": "pr", "number": 12, "person": "luis", "assignees": [], "pages": ["slam"]}],
}


def question_text(ev):
    kind, payload = dp.build_message("issues", ev, GRAPH)
    assert kind == "question"
    return payload["content"]


FILLED = """\
<!-- Answer each part in a line or two. -->

## Who
<!-- Your name -->
Max, review: Luis

## What
Remember objects YOLO has seen.

## Why
Mapping a room is easier when Oak knows where the chairs are.

## Before
Every detection was forgotten after one frame.

## After
Objects stay in a local memory with their map position.

## How to test
Run the mock camera and check /objects.

## Wiki
Updated object-detection.
"""

PARTLY = """\
## Who
<!-- Your name -->

## What
Faster frontier search.

## Why
<!-- Why does Oak need it? -->

**Before:** the explorer froze on big maps.
After: it picks a goal in under a second.
"""

EMPTY_TEMPLATE = Path(HERE).parents[2].joinpath(".github", "pull_request_template.md").read_text(encoding="utf-8") \
    if Path(HERE).parents[2].joinpath(".github", "pull_request_template.md").exists() else "## Who\n<!-- x -->\n"

PR_SKILL = """\
<!-- via /pr -->
Oak now remembers objects it has seen, so room maps can show where things are.

- Before: each detection vanished after one frame. After: objects stay in a local memory.
- Before: no way to ask what Oak saw. After: /objects lists them.

Watch: nothing risky
Ask: is a 30 second forget time right?

<details><summary>How it works (engineer detail)</summary>

**The pieces** - memory node - keeps objects
</details>

wiki: no change needed - docs only
"""


def pr_event(action="opened", body=FILLED, reviewers=("LuisMend12",), **extra):
    pr = {"number": 12, "title": "Object memory", "html_url": "https://github.com/x/y/pull/12",
          "user": {"login": "maxhawksby"}, "labels": [], "body": body, "draft": False,
          "requested_reviewers": [{"login": r} for r in reviewers],
          "created_at": "2026-10-20T09:00:00Z", "updated_at": "2026-10-20T10:00:00Z"}
    pr.update(extra)
    return {"action": action, "pull_request": pr}


def fields(payload):
    return {f["name"]: f["value"] for f in payload["embeds"][0]["fields"]}


class TestTemplate(unittest.TestCase):
    def test_filled(self):
        sec = dp.parse_template(FILLED)
        self.assertEqual(sec["who"], "Max, review: Luis")
        self.assertEqual(sec["what"], "Remember objects YOLO has seen.")
        self.assertEqual(sec["why"], "Mapping a room is easier when Oak knows where the chairs are.")
        self.assertEqual(sec["before"], "Every detection was forgotten after one frame.")
        self.assertEqual(sec["after"], "Objects stay in a local memory with their map position.")
        self.assertEqual(sec["how to test"], "Run the mock camera and check /objects.")
        self.assertEqual(sec["wiki"], "Updated object-detection.")

    def test_partly_filled(self):
        sec = dp.parse_template(PARTLY)
        self.assertNotIn("who", sec)  # only a prompt comment
        self.assertNotIn("why", sec)
        self.assertEqual(sec["what"], "Faster frontier search.")
        self.assertEqual(sec["before"], "the explorer froze on big maps.")
        self.assertEqual(sec["after"], "it picks a goal in under a second.")

    def test_empty_template(self):
        sec = dp.parse_template(EMPTY_TEMPLATE)
        self.assertEqual({k: v for k, v in sec.items()}, {})
        self.assertEqual(dp.parse_template(""), {})
        self.assertEqual(dp.parse_template(None), {})

    def test_pr_skill_three_layers(self):
        sec = dp.parse_template(PR_SKILL)
        self.assertEqual(sec["_first"], "Oak now remembers objects it has seen, so room maps can show where things are.")
        self.assertEqual(sec["before"], "- each detection vanished after one frame.\n- no way to ask what Oak saw.")
        self.assertEqual(sec["after"], "- objects stay in a local memory.\n- /objects lists them.")
        self.assertEqual(sec["wiki"], "no change needed - docs only")
        self.assertNotIn("why", sec)

    def test_sentence_starting_with_a_section_word_is_not_a_heading(self):
        sec = dp.parse_template("## What\nWhat a change.\nWhy not.\n")
        self.assertEqual(sec["what"], "What a change.\nWhy not.")


class TestDiscord(unittest.TestCase):
    def test_question_mentions_owner_with_discord_id(self):
        ev = {"action": "opened", "issue": issue(["question", "wiki:slam"], user="maxhawksby")}
        text = question_text(ev)
        self.assertIn("**Question** from Max on [SLAM](<https://github.com/maxhawksby/go2-fusion/blob/master/"
                      "docs/wiki/slam.md>): How does SLAM localize?", text)
        self.assertIn("https://github.com/x/y/issues/7", text)
        self.assertIn("<@123456789>", text)  # Luis has open work on slam

    def test_question_falls_back_to_last_changer_by_name(self):
        ev = {"action": "opened", "issue": issue(["question", "wiki:voice"], user="newbie")}
        text = question_text(ev)
        self.assertIn("from newbie", text)
        self.assertTrue(text.endswith("Can you help? Max"))

    def test_labeled_echo_and_other_labels_are_skipped(self):
        echo = issue(["question", "wiki:slam"], updated_at="2026-10-20T09:00:05Z")
        self.assertIsNone(dp.build_message("issues", {"action": "labeled", "label": {"name": "question"},
                                                      "issue": echo}, GRAPH))
        self.assertIsNone(dp.build_message("issues", {"action": "labeled", "label": {"name": "wiki:slam"},
                                                      "issue": issue(["question", "wiki:slam"])}, GRAPH))
        later = question_text({"action": "labeled", "label": {"name": "question"},
                               "issue": issue(["question", "wiki:slam"])})
        self.assertIn("**Question**", later)
        self.assertIsNone(dp.build_message("issues", {"action": "opened", "issue": issue(["wiki:slam"])}, GRAPH))

    def test_review_post_from_filled_template(self):
        kind, payload = dp.build_message("pull_request_target", pr_event(), GRAPH)
        self.assertEqual(kind, "review")
        self.assertEqual(payload["content"], "**Review requested** from <@123456789>: <https://github.com/x/y/pull/12>")
        f = fields(payload)
        self.assertEqual(f["Who"], "Max (@maxhawksby)\nMax, review: Luis")
        self.assertEqual(f["What"], "**Object memory**\nRemember objects YOLO has seen.")
        self.assertEqual(f["Why"], "Mapping a room is easier when Oak knows where the chairs are.")
        self.assertEqual(f["Before"], "Every detection was forgotten after one frame.")
        self.assertEqual(f["After"], "Objects stay in a local memory with their map position.")
        self.assertEqual(f["Wiki pages"], "[SLAM](https://github.com/maxhawksby/go2-fusion/blob/master/docs/wiki/slam.md)")
        self.assertEqual(f["Review it"], "https://github.com/x/y/pull/12")
        embed = payload["embeds"][0]
        self.assertEqual(embed["color"], 0xFF4D5E)  # Max's color
        self.assertEqual(embed["url"], "https://github.com/x/y/pull/12")
        self.assertNotIn("footer", embed)

    def test_review_post_unfilled_falls_back_to_first_paragraph(self):
        _, payload = dp.build_message("pull_request_target", pr_event(body=PR_SKILL, number=99), GRAPH)
        f = fields(payload)
        self.assertEqual(f["Why"], "Oak now remembers objects it has seen, so room maps can show where things are.")
        self.assertTrue(f["Before"].startswith("- each detection vanished"))
        self.assertEqual(f["Wiki pages"], "no change needed - docs only")
        self.assertIn("first paragraph", payload["embeds"][0]["footer"]["text"])

        _, payload = dp.build_message("pull_request_target", pr_event(body=EMPTY_TEMPLATE, number=99), GRAPH)
        f = fields(payload)
        self.assertEqual((f["Why"], f["Before"], f["After"], f["Wiki pages"]),
                         ("not filled in", "not filled in", "not filled in", "none listed"))
        self.assertEqual(payload["embeds"][0]["footer"]["text"], "Template not filled in.")

    def test_review_without_reviewer_mentions_page_owners(self):
        ev = pr_event(reviewers=(), user={"login": "newbie"})
        _, payload = dp.build_message("pull_request_target", ev, GRAPH)
        self.assertTrue(payload["content"].startswith("**Review requested** - page owners: <@123456789>"))
        self.assertEqual(fields(payload)["Who"], "@newbie\nMax, review: Luis")
        self.assertNotIn("color", payload["embeds"][0])

    def test_one_post_per_review_request(self):
        post = lambda ev: dp.build_message("pull_request_target", ev, GRAPH)  # noqa: E731
        self.assertIsNone(post(pr_event(draft=True)))  # drafts wait for ready_for_review
        self.assertIsNotNone(post(pr_event("ready_for_review")))
        # opened with reviewers: GitHub also fires review_requested seconds later
        echo = pr_event("review_requested", updated_at="2026-10-20T09:00:03Z")
        echo["requested_reviewer"] = {"login": "LuisMend12"}
        self.assertIsNone(post(echo))
        # two reviewers asked at once later: one event per reviewer, one post
        both = ("maxhawksby", "LuisMend12")
        first = pr_event("review_requested", reviewers=both)
        first["requested_reviewer"] = {"login": "maxhawksby"}
        last = pr_event("review_requested", reviewers=both)
        last["requested_reviewer"] = {"login": "LuisMend12"}
        self.assertIsNone(post(first))
        self.assertIn("Max <@123456789>", post(last)[1]["content"])
        drafted = pr_event("review_requested", draft=True)
        drafted["requested_reviewer"] = {"login": "LuisMend12"}
        self.assertIsNone(post(drafted))

    def test_other_pr_actions_ignored(self):
        self.assertIsNone(dp.build_message("pull_request", {"action": "synchronize", "pull_request": {}}, GRAPH))

    def test_as_text_for_the_log(self):
        _, payload = dp.build_message("pull_request_target", pr_event(), GRAPH)
        text = dp.as_text(payload)
        self.assertIn("Why: Mapping a room", text)
        self.assertIn("Review it: https://github.com/x/y/pull/12", text)


class TestWebhooks(unittest.TestCase):
    def test_review_and_question_routing(self):
        env = {"DISCORD_REVIEW_WEBHOOK_URL": "r", "DISCORD_QUESTIONS_WEBHOOK_URL": "q", "DISCORD_WEBHOOK_URL": "o"}
        self.assertEqual(dp.webhook_for("review", env), ("DISCORD_REVIEW_WEBHOOK_URL", "r"))
        self.assertEqual(dp.webhook_for("question", env), ("DISCORD_QUESTIONS_WEBHOOK_URL", "q"))

    def test_fallbacks(self):
        self.assertEqual(dp.webhook_for("question", {"DISCORD_REVIEW_WEBHOOK_URL": "r"}),
                         ("DISCORD_REVIEW_WEBHOOK_URL", "r"))
        self.assertEqual(dp.webhook_for("question", {"DISCORD_WEBHOOK_URL": "o", "DISCORD_QUESTIONS_WEBHOOK_URL": " "}),
                         ("DISCORD_WEBHOOK_URL", "o"))
        self.assertEqual(dp.webhook_for("review", {"DISCORD_WEBHOOK_URL": "o"}), ("DISCORD_WEBHOOK_URL", "o"))
        self.assertEqual(dp.webhook_for("review", {"DISCORD_QUESTIONS_WEBHOOK_URL": "q"}), (None, ""))

    def test_no_webhook_exits_zero(self):
        names = ["DISCORD_WEBHOOK_URL", "DISCORD_REVIEW_WEBHOOK_URL", "DISCORD_QUESTIONS_WEBHOOK_URL", "GITHUB_EVENT_NAME"]
        old = {n: os.environ.pop(n, None) for n in names}
        try:
            self.assertEqual(dp.main(), 0)
            os.environ["GITHUB_EVENT_NAME"] = "issues"
            self.assertEqual(dp.main(), 0)
        finally:
            for n, v in old.items():
                os.environ.pop(n, None)
                if v is not None:
                    os.environ[n] = v


if __name__ == "__main__":
    unittest.main()
