"""Tests for scripts/generate_project_index.py (standard library only)."""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import generate_project_index as gpi  # noqa: E402


def repo(name="demo-app", **over):
    base = {
        "name": name,
        "html_url": f"https://github.com/Salihefendihsa/{name}",
        "owner": {"login": "Salihefendihsa"},
        "private": False,
        "visibility": "public",
        "fork": False,
        "archived": False,
        "disabled": False,
        "description": "A useful application.",
        "language": "TypeScript",
        "homepage": "",
        "pushed_at": "2026-05-01T00:00:00Z",
        "topics": ["portfolio"],
    }
    base.update(over)
    return base


README = (
    "# Title\n\nintro\n\n"
    f"{gpi.START_MARKER}\nold\n{gpi.END_MARKER}\n\n## How I Build\n"
)


class SelectionTests(unittest.TestCase):
    def test_repo_without_topic_is_excluded(self):
        self.assertEqual(gpi.select_and_sort([repo(topics=[])]), [])

    def test_private_repo_is_excluded(self):
        self.assertEqual(gpi.select_and_sort([repo(private=True, visibility="private")]), [])

    def test_fork_is_excluded(self):
        self.assertEqual(gpi.select_and_sort([repo(fork=True)]), [])

    def test_archived_is_excluded(self):
        self.assertEqual(gpi.select_and_sort([repo(archived=True)]), [])

    def test_disabled_is_excluded(self):
        self.assertEqual(gpi.select_and_sort([repo(disabled=True)]), [])

    def test_empty_description_is_excluded(self):
        self.assertEqual(gpi.select_and_sort([repo(description="   ")]), [])
        self.assertEqual(gpi.select_and_sort([repo(description=None)]), [])

    def test_profile_repo_is_excluded(self):
        self.assertEqual(gpi.select_and_sort([repo(name="Salihefendihsa")]), [])

    def test_other_owner_is_excluded(self):
        self.assertEqual(gpi.select_and_sort([repo(owner={"login": "someone-else"})]), [])

    def test_eligible_repo_is_included(self):
        self.assertEqual(len(gpi.select_and_sort([repo()])), 1)


class OrderingTests(unittest.TestCase):
    def test_featured_sorts_first_then_by_push_date(self):
        older_featured = repo("a-featured", topics=["portfolio", "featured"], pushed_at="2025-01-01T00:00:00Z")
        newest = repo("b-new", pushed_at="2026-06-01T00:00:00Z")
        middle = repo("c-mid", pushed_at="2026-01-01T00:00:00Z")
        names = [r["name"] for r in gpi.select_and_sort([middle, newest, older_featured])]
        self.assertEqual(names, ["a-featured", "b-new", "c-mid"])

    def test_deterministic_for_same_input(self):
        repos = [repo("x", pushed_at="2026-01-01T00:00:00Z"), repo("y", pushed_at="2026-01-01T00:00:00Z")]
        first = gpi.render_block(gpi.select_and_sort(list(repos)))
        second = gpi.render_block(gpi.select_and_sort(list(reversed(repos))))
        self.assertEqual(first, second)


class RenderTests(unittest.TestCase):
    def test_category_and_status_are_resolved(self):
        out = gpi.render_entry(repo(topics=["portfolio", "category-mobile", "status-building"]))
        self.assertIn("`Mobile`", out)
        self.assertIn("`Building`", out)
        self.assertEqual(gpi.category_of(["category-ai"]), "AI")
        self.assertIsNone(gpi.category_of(["portfolio"]))

    def test_no_homepage_means_no_live_demo(self):
        self.assertNotIn("Live Demo", gpi.render_entry(repo(homepage="")))
        self.assertNotIn("Live Demo", gpi.render_entry(repo(homepage=None)))
        self.assertIn("[Live Demo](https://example.com)", gpi.render_entry(repo(homepage="https://example.com")))

    def test_non_http_homepage_is_ignored(self):
        self.assertNotIn("Live Demo", gpi.render_entry(repo(homepage="javascript:alert(1)")))

    def test_markdown_special_characters_are_escaped(self):
        out = gpi.render_entry(repo(name="weird[name]", description="Uses *bold* and _under_ <b>tags</b> | pipes"))
        self.assertIn(r"weird\[name\]", out)
        self.assertIn(r"\*bold\*", out)
        self.assertIn(r"\<b\>tags\</b\>", out)
        self.assertNotIn("<b>", out)

    def test_entry_shape(self):
        out = gpi.render_entry(repo(language="C#", topics=["portfolio", "category-backend", "status-live"], homepage="https://x.dev"))
        self.assertTrue(out.startswith("### [demo-app](https://github.com/Salihefendihsa/demo-app)"))
        self.assertIn("`C#` · `Backend` · `Live`<br>", out)
        self.assertIn("[Repository](https://github.com/Salihefendihsa/demo-app) · [Live Demo](https://x.dev)", out)

    def test_block_contains_markers_and_heading(self):
        block = gpi.render_block([repo()])
        self.assertTrue(block.startswith(gpi.START_MARKER))
        self.assertTrue(block.endswith(gpi.END_MARKER))
        self.assertIn("## Project Index", block)


class ReadmeUpdateTests(unittest.TestCase):
    def test_only_marker_region_changes(self):
        new = gpi.update_readme_text(README, [repo()])
        self.assertTrue(new.startswith("# Title\n\nintro\n\n"))
        self.assertTrue(new.endswith("\n\n## How I Build\n"))
        self.assertNotIn("\nold\n", new)
        self.assertIn("### [demo-app]", new)

    def test_missing_markers_raises_and_readme_unchanged(self):
        with self.assertRaises(gpi.IndexError_):
            gpi.update_readme_text("# no markers here\n", [repo()])

    def test_empty_result_keeps_existing_entries(self):
        populated = gpi.update_readme_text(README, [repo()])
        again = gpi.update_readme_text(populated, [])
        self.assertEqual(populated, again)

    def test_empty_result_on_fresh_readme_writes_note(self):
        out = gpi.update_readme_text(README, [])
        self.assertIn(gpi.EMPTY_NOTE, out)


class FetchTests(unittest.TestCase):
    class _Resp(io.BytesIO):
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def test_pagination_is_followed(self):
        pages = {1: [repo(f"r{i}") for i in range(gpi.PER_PAGE)], 2: [repo("last")]}
        seen = []
        def opener(req, timeout=None):
            page = int(__import__("re").search(r"[?&]page=(\d+)", req.full_url).group(1))
            seen.append(page)
            self.assertIn("timeout", {"timeout": timeout})
            return self._Resp(json.dumps(pages[page]).encode())
        out = gpi.fetch_public_repos(opener=opener)
        self.assertEqual(len(out), gpi.PER_PAGE + 1)
        self.assertEqual(seen, [1, 2])

    def test_api_error_raises_index_error(self):
        def opener(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 503, "unavailable", {}, None)
        with self.assertRaises(gpi.IndexError_):
            gpi.fetch_public_repos(opener=opener)

    def test_token_is_sent_but_never_logged(self):
        os.environ["GITHUB_TOKEN"] = "ghs_dummy_value_for_test"
        try:
            headers = {}
            def opener(req, timeout=None):
                headers.update(req.headers)
                return self._Resp(b"[]")
            gpi.fetch_public_repos(opener=opener)
            self.assertIn("Authorization", headers)
            def failing(req, timeout=None):
                raise urllib.error.URLError("boom")
            with self.assertRaises(gpi.IndexError_) as ctx:
                gpi.fetch_public_repos(opener=failing)
            self.assertNotIn("ghs_dummy", str(ctx.exception))
        finally:
            os.environ.pop("GITHUB_TOKEN", None)


class MainTests(unittest.TestCase):
    def _run(self, readme_text, repos_json, extra=()):
        tmp = tempfile.mkdtemp()
        readme = os.path.join(tmp, "README.md")
        with open(readme, "w", encoding="utf-8") as fh:
            fh.write(readme_text)
        data = os.path.join(tmp, "repos.json")
        with open(data, "w", encoding="utf-8") as fh:
            json.dump(repos_json, fh)
        code = gpi.main(["--readme", readme, "--input", data, "--output", os.path.join(tmp, "gen", "projects.md"), *extra])
        with open(readme, encoding="utf-8") as fh:
            return code, fh.read(), tmp

    def test_main_writes_index_and_is_idempotent(self):
        code, text, tmp = self._run(README, [repo()])
        self.assertEqual(code, 0)
        self.assertIn("### [demo-app]", text)
        self.assertTrue(os.path.exists(os.path.join(tmp, "gen", "projects.md")))
        data = os.path.join(tmp, "repos.json")
        code2 = gpi.main(["--readme", os.path.join(tmp, "README.md"), "--input", data, "--output", ""])
        with open(os.path.join(tmp, "README.md"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), text)
        self.assertEqual(code2, 0)

    def test_main_without_markers_fails_and_leaves_file(self):
        code, text, _ = self._run("# plain\n", [repo()])
        self.assertEqual(code, 1)
        self.assertEqual(text, "# plain\n")

    def test_main_api_failure_leaves_readme(self):
        tmp = tempfile.mkdtemp()
        readme = os.path.join(tmp, "README.md")
        with open(readme, "w", encoding="utf-8") as fh:
            fh.write(README)
        original = gpi.fetch_public_repos
        gpi.fetch_public_repos = lambda *a, **k: (_ for _ in ()).throw(gpi.IndexError_("API down"))
        try:
            code = gpi.main(["--readme", readme, "--output", ""])
        finally:
            gpi.fetch_public_repos = original
        self.assertEqual(code, 1)
        with open(readme, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), README)


if __name__ == "__main__":
    unittest.main()
