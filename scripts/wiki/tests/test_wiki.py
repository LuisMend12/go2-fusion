"""Tests for check_wiki.py and mirror_to_wiki.py.

Run from the repo root:  python3 -m unittest discover -s scripts/wiki/tests -v

Each test copies fixture/ (a tiny repo with a center page, 2 hubs and 2
program pages) into a temp folder, makes it a git repo with one commit on
master, then plants one problem and checks the checker catches it.
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import check_wiki  # noqa: E402
import mirror_to_wiki  # noqa: E402

FIXTURE = os.path.join(HERE, "fixture")
GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com",
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
}


class FixtureRepo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wiki-test-")
        self.root = os.path.join(self.tmp, "repo")
        shutil.copytree(FIXTURE, self.root)
        self.git("init", "-q", "-b", "master")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("switch", "-q", "-c", "feature")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.root, env=GIT_ENV, check=True, capture_output=True)

    def write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def read(self, rel):
        with open(os.path.join(self.root, rel), encoding="utf-8") as f:
            return f.read()

    def commit(self, msg="change"):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg)

    def check(self, base="master", pr_body=""):
        out = io.StringIO()
        code = check_wiki.run(self.root, base, pr_body, out=out)
        return code, out.getvalue()


class TestCheckWiki(FixtureRepo):
    def test_clean_fixture_passes(self):
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("Wiki check passed: 5 page(s)", out)

    def test_no_wiki_folder_passes_with_note(self):
        shutil.rmtree(os.path.join(self.root, "docs", "wiki"))
        code, out = self.check()
        self.assertEqual(code, 0)
        self.assertIn("does not exist yet", out)

    # a. titles, parents, links
    def test_missing_title_fails(self):
        self.write("docs/wiki/movement.md", "---\nparent: oak\n---\n# Movement\n")
        code, out = self.check(base=None)
        self.assertEqual(code, 1)
        self.assertIn("docs/wiki/movement.md has no title", out)

    def test_missing_front_matter_fails(self):
        self.write("docs/wiki/movement.md", "# Movement\n")
        code, out = self.check(base=None)
        self.assertEqual(code, 1)
        self.assertIn("has no front matter", out)

    def test_unknown_parent_fails(self):
        text = self.read("docs/wiki/keyboard-teleop.md").replace("parent: movement", "parent: motion")
        self.write("docs/wiki/keyboard-teleop.md", text)
        code, out = self.check(base=None)
        self.assertEqual(code, 1)
        self.assertIn("parent is 'motion', but there is no page docs/wiki/motion.md", out)

    def test_broken_link_fails(self):
        self.write("docs/wiki/movement.md", self.read("docs/wiki/movement.md") + "\nSee [gone](gone.md).\n")
        code, out = self.check(base=None)
        self.assertEqual(code, 1)
        self.assertIn("links to 'gone.md', but docs/wiki/gone.md does not exist", out)

    def test_links_in_code_blocks_are_ignored(self):
        # object-detection.md has [not a link](missing.md) inside a ``` block.
        code, out = self.check(base=None)
        self.assertEqual(code, 0, out)

    def test_reserved_oak_slug_fails(self):
        self.write("docs/wiki/oak.md", "---\ntitle: Oak\nparent: oak\n---\n")
        code, out = self.check(base=None)
        self.assertEqual(code, 1)
        self.assertIn("reserved for the center page", out)

    # b. every page reaches README.md
    def test_parent_loop_fails(self):
        self.write("docs/wiki/a.md", "---\ntitle: A\nparent: b\n---\n")
        self.write("docs/wiki/b.md", "---\ntitle: B\nparent: a\n---\n")
        code, out = self.check(base=None)
        self.assertEqual(code, 1)
        self.assertIn("parents go in a circle (a -> b -> a)", out)

    # c. drift
    def test_code_change_without_page_change_fails(self):
        self.write("src/object_detection/detector.py", 'print("detect faster")\n')
        self.commit()
        code, out = self.check()
        self.assertEqual(code, 1)
        self.assertIn(
            "You changed src/object_detection/detector.py, but its wiki page "
            "docs/wiki/object-detection.md did not change.", out)
        self.assertIn("wiki: no change needed - <reason>", out)

    def test_uncommitted_code_change_is_also_caught(self):
        self.write("src/keyboard_teleop/teleop.py", 'print("new keys")\n')
        code, out = self.check()
        self.assertEqual(code, 1)
        self.assertIn("docs/wiki/keyboard-teleop.md did not change", out)

    def test_code_change_with_page_change_passes(self):
        self.write("src/object_detection/detector.py", 'print("detect faster")\n')
        self.write("docs/wiki/object-detection.md",
                   self.read("docs/wiki/object-detection.md") + "\nNow faster.\n")
        self.commit()
        code, out = self.check()
        self.assertEqual(code, 0, out)

    def test_pr_body_skip_line_passes(self):
        self.write("src/object_detection/detector.py", 'print("detect faster")\n')
        self.commit()
        body = "Speeds up detection.\n\nwiki: no change needed - only a variable rename\n"
        code, out = self.check(pr_body=body)
        self.assertEqual(code, 0, out)

    def test_pr_body_skip_line_needs_a_reason(self):
        self.write("src/object_detection/detector.py", 'print("detect faster")\n')
        self.commit()
        code, _ = self.check(pr_body="wiki: no change needed -")
        self.assertEqual(code, 1)

    def test_unrelated_change_passes(self):
        self.write("notes.txt", "hello\n")
        self.commit()
        code, out = self.check()
        self.assertEqual(code, 0, out)

    def test_bad_base_ref_fails_clearly(self):
        code, out = self.check(base="origin/nope")
        self.assertEqual(code, 1)
        self.assertIn("Could not compare your branch with 'origin/nope'", out)

    # d. coverage
    def test_new_package_without_page_fails(self):
        self.write("src/speech_processor/speak.py", "print('hi')\n")
        code, out = self.check(base=None)
        self.assertEqual(code, 1)
        self.assertIn("src/speech_processor has no wiki page", out)

    def test_new_package_with_page_passes(self):
        self.write("src/speech_processor/speak.py", "print('hi')\n")
        self.write("docs/wiki/speech.md",
                   "---\ntitle: Speech\nparent: oak\ncode: [src/speech_processor/**]\n---\n")
        code, out = self.check(base=None)
        self.assertEqual(code, 0, out)


class TestParsing(unittest.TestCase):
    def test_front_matter_inline_and_block_lists(self):
        meta, body, has = check_wiki.parse_front_matter(
            "---\ntitle: \"A: B\"  # note\nparent: oak\ncode: [src/a/**, 'src/b/*.py']\n"
            "extra:\n  - one\n  - two\n---\nBody\n")
        self.assertTrue(has)
        self.assertEqual(meta["title"], "A: B")
        self.assertEqual(meta["code"], ["src/a/**", "src/b/*.py"])
        self.assertEqual(meta["extra"], ["one", "two"])
        self.assertEqual(body, "Body\n")

    def test_no_front_matter(self):
        meta, body, has = check_wiki.parse_front_matter("# Title\n")
        self.assertFalse(has)
        self.assertEqual(meta, {})

    def test_globs(self):
        m = check_wiki.matches_any
        self.assertTrue(m("src/a/x/y.py", ["src/a/**"]))
        self.assertFalse(m("src/ab/y.py", ["src/a/**"]))
        self.assertTrue(m("src/a/y.py", ["src/a/*.py"]))
        self.assertFalse(m("src/a/x/y.py", ["src/a/*.py"]))
        self.assertTrue(m("src/a/x/y.py", ["src/**/y.py"]))
        self.assertTrue(m("src/a/y.py", ["src/**/y.py"]))
        self.assertTrue(m("src/a/y.py", ["src/a"]))
        self.assertTrue(m("host_tools/stt/run.py", ["./host_tools/"]))


class TestMirror(FixtureRepo):
    REPO = "team/go2-fusion"

    def render(self, slug):
        pages = check_wiki.load_pages(self.root)
        names = mirror_to_wiki.build_name_map(pages)
        return mirror_to_wiki.render_page(pages[slug], names, self.REPO, "master")

    def test_link_rewriting(self):
        out = self.render("object-detection")
        self.assertNotIn("title:", out)  # front matter stripped
        self.assertIn("[Senses](Senses#programs)", out)
        self.assertIn("[code](https://github.com/team/go2-fusion/blob/master/src/object_detection/detector.py)", out)
        self.assertIn("[not a link](missing.md)", out)  # code block untouched
        self.assertIn("Edit this page in the repo: "
                      "<https://github.com/team/go2-fusion/blob/master/docs/wiki/object-detection.md>", out)

    def test_center_and_hub_links(self):
        self.assertIn("[Senses](Senses)", self.render("oak"))
        hub = self.render("senses")
        self.assertIn("[Object detection](Object-detection)", hub)
        self.assertIn("[Oak](Home)", hub)

    def test_images_use_raw_urls(self):
        self.assertIn("![diagram](https://github.com/team/go2-fusion/raw/master/docs/img/teleop.png)",
                      self.render("keyboard-teleop"))

    def test_external_and_inline_code_links_untouched(self):
        self.write("docs/wiki/movement.md",
                   "---\ntitle: Movement\nparent: oak\n---\n[ROS](https://ros.org) `[x](y.md)` [top](#top)\n")
        out = self.render("movement")
        self.assertIn("[ROS](https://ros.org) `[x](y.md)` [top](#top)", out)

    def test_mirror_writes_files_and_removes_stale_pages(self):
        out_dir = os.path.join(self.tmp, "wiki")
        os.makedirs(out_dir)
        with open(os.path.join(out_dir, "Old-page.md"), "w") as f:
            f.write("stale")
        written = mirror_to_wiki.mirror(self.root, out_dir, self.REPO, "master")
        self.assertEqual(written, ["Home.md", "Keyboard-teleop.md", "Movement.md",
                                   "Object-detection.md", "Senses.md"])
        self.assertFalse(os.path.exists(os.path.join(out_dir, "Old-page.md")))

    def test_title_clash_falls_back_to_slug(self):
        self.write("docs/wiki/movement-2.md", "---\ntitle: Movement\nparent: oak\n---\n")
        names = mirror_to_wiki.build_name_map(check_wiki.load_pages(self.root))
        self.assertEqual(sorted([names["docs/wiki/movement.md"], names["docs/wiki/movement-2.md"]]),
                         ["movement", "movement-2"])


if __name__ == "__main__":
    unittest.main()
