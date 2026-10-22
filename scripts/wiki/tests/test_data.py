"""Tests for build_graph.py (graph.json v2 data) and discord_ping.py.

Run from the repo root:  python3 -m unittest discover -s scripts/wiki/tests -v

Pure functions only, with fixtures: no network, no git.
"""
from __future__ import annotations

import math
import os
import sys
import unittest

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


class TestDiscord(unittest.TestCase):
    def test_question_mentions_owner_with_discord_id(self):
        ev = {"action": "opened", "issue": issue(["question", "wiki:slam"], user="maxhawksby")}
        text = dp.build_message("issues", ev, GRAPH)
        self.assertIn("**Question** from Max on [SLAM](<https://github.com/maxhawksby/go2-fusion/blob/master/"
                      "docs/wiki/slam.md>): How does SLAM localize?", text)
        self.assertIn("https://github.com/x/y/issues/7", text)
        self.assertIn("<@123456789>", text)  # Luis has open work on slam

    def test_question_falls_back_to_last_changer_by_name(self):
        ev = {"action": "opened", "issue": issue(["question", "wiki:voice"], user="newbie")}
        text = dp.build_message("issues", ev, GRAPH)
        self.assertIn("from newbie", text)
        self.assertTrue(text.endswith("Can you help? Max"))

    def test_labeled_echo_and_other_labels_are_skipped(self):
        echo = issue(["question", "wiki:slam"], updated_at="2026-10-20T09:00:05Z")
        self.assertIsNone(dp.build_message("issues", {"action": "labeled", "label": {"name": "question"},
                                                      "issue": echo}, GRAPH))
        self.assertIsNone(dp.build_message("issues", {"action": "labeled", "label": {"name": "wiki:slam"},
                                                      "issue": issue(["question", "wiki:slam"])}, GRAPH))
        later = dp.build_message("issues", {"action": "labeled", "label": {"name": "question"},
                                            "issue": issue(["question", "wiki:slam"])}, GRAPH)
        self.assertIn("**Question**", later)
        self.assertIsNone(dp.build_message("issues", {"action": "opened", "issue": issue(["wiki:slam"])}, GRAPH))

    def test_review_request(self):
        ev = {"action": "review_requested", "requested_reviewer": {"login": "LuisMend12"},
              "pull_request": {"number": 12, "title": "Tune SLAM", "html_url": "https://github.com/x/y/pull/12",
                               "user": {"login": "maxhawksby"}, "labels": []}}
        text = dp.build_message("pull_request_target", ev, GRAPH)
        self.assertIn("**Review requested** by Max on [SLAM]", text)
        self.assertIn("Reviewer: <@123456789>", text)
        self.assertNotIn("Page owners", text)  # Luis is already the reviewer, Max is the author

    def test_other_pr_actions_ignored(self):
        self.assertIsNone(dp.build_message("pull_request", {"action": "synchronize", "pull_request": {}}, GRAPH))

    def test_no_webhook_exits_zero(self):
        old = os.environ.pop("DISCORD_WEBHOOK_URL", None)
        try:
            self.assertEqual(dp.main(), 0)
        finally:
            if old is not None:
                os.environ["DISCORD_WEBHOOK_URL"] = old


if __name__ == "__main__":
    unittest.main()
