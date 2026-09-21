"""Tests for scripts/generate_project_index.py (standard library only)."""
from __future__ import annotations

import io
import json
import os
import re
import sys
import tempfile
import unittest
import urllib.error

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import generate_project_index as gpi  # noqa: E402

OWNER = gpi.OWNER


def repo(name="demo-app", **over):
    base = {
        "name": name,
        "html_url": f"https://github.com/{OWNER}/{name}",
        "owner": {"login": OWNER},
        "private": False,
        "visibility": "public",
        "fork": False,
        "archived": False,
        "disabled": False,
        "description": "A useful application.",
        "language": "TypeScript",
        "homepage": "",
        "pushed_at": "2026-05-01T00:00:00Z",
        "topics": [],
    }
    base.update(over)
    return base


def entry(display_name="Private Thing", **over):
    base = {
        "display_name": display_name,
        "safe_summary": "Does a private thing well.",
        "stack": "Python",
        "role": "Solo engineer",
        "access": "Private",
        "status": "In development",
        "category": "Products & Platforms",
        "optional_public_url": "",
        "featured": False,
        "sort_order": 10,
    }
    base.update(over)
    return base


def catalog(entries=None, overrides=None):
    return {"version": 1, "entries": entries or [], "public_overrides": overrides or {}}


README = (
    "# Title\n\nintro\n\n"
    f"{gpi.START_MARKER}\nold\n{gpi.END_MARKER}\n\n## Core Expertise\n"
)


def build(repos=None, entries=None, overrides=None):
    return gpi.build_projects(repos or [], catalog(entries, overrides))


def by_name(projects, name):
    return next(p for p in projects if p.name == name)


# --------------------------------------------------------------------------- public repositories

class PublicRepoTests(unittest.TestCase):
    def test_public_owner_repo_is_listed_with_link(self):
        p = by_name(build([repo()]), "demo-app")
        self.assertEqual(p.url, f"https://github.com/{OWNER}/demo-app")
        self.assertEqual(p.access, "Public")
        self.assertEqual(p.source, "public")

    def test_private_repo_from_api_is_never_listed(self):
        self.assertEqual(build([repo(private=True, visibility="private")]), [])

    def test_fork_disabled_profile_and_other_owner_are_excluded(self):
        self.assertEqual(build([repo(fork=True)]), [])
        self.assertEqual(build([repo(disabled=True)]), [])
        self.assertEqual(build([repo(name=OWNER)]), [])
        self.assertEqual(build([repo(owner={"login": "someone-else"})]), [])

    def test_profile_hide_topic_hides_repo(self):
        self.assertEqual(build([repo(topics=["profile-hide"])]), [])

    def test_archived_repo_or_topic_goes_to_archived_group(self):
        self.assertEqual(by_name(build([repo(archived=True)]), "demo-app").category, gpi.ARCHIVED_CATEGORY)
        self.assertEqual(by_name(build([repo(topics=["archived"])]), "demo-app").category, gpi.ARCHIVED_CATEGORY)

    def test_academic_topics_go_to_academic_group(self):
        for topic in ("academic", "experimental", "lab"):
            self.assertEqual(by_name(build([repo(topics=[topic])]), "demo-app").category, gpi.ACADEMIC_CATEGORY)

    def test_category_topics_and_language_fallback(self):
        self.assertEqual(by_name(build([repo(topics=["category-ai"])]), "demo-app").category, "AI & Automation")
        self.assertEqual(by_name(build([repo(topics=["category-backend"])]), "demo-app").category, "Backend & APIs")
        self.assertEqual(by_name(build([repo(language="C#")]), "demo-app").category, "Desktop & Tools")
        self.assertEqual(by_name(build([repo(language="TypeScript")]), "demo-app").category, "Web & Mobile")
        self.assertEqual(by_name(build([repo(language=None)]), "demo-app").category, gpi.ACADEMIC_CATEGORY)

    def test_status_topic_is_resolved(self):
        self.assertEqual(by_name(build([repo(topics=["status-live"])]), "demo-app").status, "Live")

    def test_empty_description_uses_safe_fallback(self):
        p = by_name(build([repo(description="   ", language="Python")]), "demo-app")
        self.assertEqual(p.summary, "Python repository; description not published yet.")

    def test_override_replaces_summary_stack_category_and_display_name(self):
        ov = {"demo-app": {"display_name": "Demo App", "safe_summary": "Curated text.", "stack": "Next.js", "category": "Products & Platforms"}}
        p = by_name(build([repo(description="")], overrides=ov), "Demo App")
        self.assertEqual((p.summary, p.stack, p.category), ("Curated text.", "Next.js", "Products & Platforms"))
        self.assertEqual(p.url, f"https://github.com/{OWNER}/demo-app")

    def test_override_comment_key_is_ignored(self):
        self.assertEqual(len(build([repo()], overrides={"$comment": "note"})), 1)

    def test_unexpected_html_url_is_rejected(self):
        with self.assertRaises(gpi.IndexError_):
            build([repo(html_url="https://evil.example.com/x")])


class HomepageTests(unittest.TestCase):
    def test_valid_homepage_becomes_live_link(self):
        p = by_name(build([repo(homepage="https://demo.example.com")]), "demo-app")
        self.assertEqual(p.live_url, "https://demo.example.com")
        self.assertIn("[Live](https://demo.example.com)", gpi.render_row(p))

    def test_invalid_homepages_are_not_linked(self):
        for bad in ("demo.example.com", "ftp://x.y", "javascript:alert(1)", "https://bad url.com", "https://x.com/a)b", "https://github.com/x/y"):
            p = by_name(build([repo(homepage=bad)]), "demo-app")
            self.assertEqual(p.live_url, "", bad)
            self.assertNotIn("[Live]", gpi.render_row(p), bad)


# --------------------------------------------------------------------------- catalog

class CatalogTests(unittest.TestCase):
    def test_private_catalog_item_renders_without_link(self):
        p = by_name(build(entries=[entry()]), "Private Thing")
        row = gpi.render_row(p)
        self.assertIn("**Private Thing**", row)
        self.assertNotIn("](", row.split("|")[1])
        self.assertIn("Private", row)

    def test_private_entry_with_github_url_is_refused(self):
        for access in ("Private", "Confidential", "Collaborative · Private"):
            with self.assertRaises(gpi.IndexError_, msg=access):
                gpi.validate_catalog(catalog([entry(access=access, optional_public_url=f"https://github.com/{OWNER}/secret")]))

    def test_private_entry_never_gets_github_link_even_if_validation_is_bypassed(self):
        p = gpi.project_from_entry(entry(optional_public_url="https://github.com/someone/secret"))
        self.assertEqual(p.url, "")
        self.assertEqual(p.live_url, "")

    def test_collaborative_public_entry_may_link_repo_and_shows_role(self):
        e = entry("Shared App", access="Collaborative · Public", category="Collaborative Work",
                  role="Core contributor · 40 commits", optional_public_url="https://github.com/partner/shared-app")
        p = by_name(build(entries=[e]), "Shared App")
        row = gpi.render_row(p)
        self.assertIn("[Shared App](https://github.com/partner/shared-app)", row)
        self.assertIn("<sub>Core contributor · 40 commits</sub><br><sub>Collaborative · Public</sub>", row)

    def test_collaborative_private_entry_shows_role_and_no_link(self):
        e = entry("Shared Private", access="Collaborative · Private", category="Collaborative Work", role="Lead contributor")
        row = gpi.render_row(by_name(build(entries=[e]), "Shared Private"))
        self.assertIn("**Shared Private**", row)
        self.assertIn("<sub>Lead contributor</sub><br><sub>Collaborative · Private</sub>", row)
        self.assertNotIn("github.com", row)

    def test_disallowed_fields_and_values_are_rejected(self):
        with self.assertRaises(gpi.IndexError_):
            gpi.validate_catalog(catalog([entry(repo_url="x")]))
        with self.assertRaises(gpi.IndexError_):
            gpi.validate_catalog(catalog([entry(category="Secret Stuff")]))
        with self.assertRaises(gpi.IndexError_):
            gpi.validate_catalog(catalog([entry(access="Internal")]))
        with self.assertRaises(gpi.IndexError_):
            gpi.validate_catalog(catalog([entry(optional_public_url="not a url")]))
        with self.assertRaises(gpi.IndexError_):
            gpi.validate_catalog(catalog(overrides={"x": {"internal_note": "y"}}))

    def test_academic_and_archived_catalog_entries_group_correctly(self):
        ps = build(entries=[entry("Lab", category=gpi.ACADEMIC_CATEGORY), entry("Old", category=gpi.ARCHIVED_CATEGORY)])
        block = gpi.render_block(ps)
        self.assertIn("<summary>University coursework, labs and small experiments (1)</summary>", block)
        self.assertIn("<summary>Archived / earlier work (1)</summary>", block)


# --------------------------------------------------------------------------- assembly rules

class AssemblyTests(unittest.TestCase):
    def test_duplicate_project_names_are_rejected(self):
        with self.assertRaises(gpi.IndexError_):
            build([repo("Same Name")], entries=[entry("same name")])

    def test_featured_is_capped_at_three_deterministically(self):
        entries = [entry(f"P{i}", featured=True, sort_order=i) for i in range(5)]
        ps = build([repo(topics=["featured"], pushed_at="2026-01-01T00:00:00Z")], entries=entries)
        featured = [p.name for p in ps if p.featured]
        self.assertEqual(len(featured), 3)
        self.assertEqual(featured, ["demo-app", "P0", "P1"])  # public sort_order 0 first, then catalog order

    def test_featured_sorts_first_then_push_date_then_name(self):
        ps = build([
            repo("b-old", pushed_at="2025-01-01T00:00:00Z"),
            repo("a-old", pushed_at="2025-01-01T00:00:00Z"),
            repo("new", pushed_at="2026-01-01T00:00:00Z"),
            repo("star", topics=["featured"], pushed_at="2024-01-01T00:00:00Z"),
        ])
        self.assertEqual([p.name for p in ps], ["star", "new", "a-old", "b-old"])

    def test_deterministic_and_idempotent_output(self):
        repos = [repo("z"), repo("a", topics=["category-ai"]), repo("m", language="C#")]
        entries = [entry("Q", sort_order=5), entry("P", sort_order=5, category="Collaborative Work", access="Collaborative · Private")]
        first = gpi.render_block(build(repos, entries))
        second = gpi.render_block(build(list(reversed(repos)), list(reversed(entries))))
        self.assertEqual(first, second)
        readme = gpi.update_readme_text(README, build(repos, entries))
        self.assertEqual(gpi.update_readme_text(readme, build(repos, entries)), readme)

    def test_category_order_is_fixed(self):
        repos = [repo("d", language="C#"), repo("b", topics=["category-ai"]), repo("p", topics=["category-product"]), repo("w")]
        block = gpi.render_block(build(repos))
        positions = [block.index(f"### {c}") for c in ("Products & Platforms", "AI & Automation", "Web & Mobile", "Desktop & Tools")]
        self.assertEqual(positions, sorted(positions))


# --------------------------------------------------------------------------- rendering

class RenderTests(unittest.TestCase):
    def test_markdown_and_pipe_characters_are_escaped(self):
        p = by_name(build([repo(description="a | b <script> *c* [d](e) `f`")]), "demo-app")
        row = gpi.render_row(p)
        self.assertIn("a \\| b \\<script\\> \\*c\\* \\[d\\](e) \\`f\\`", row)
        self.assertEqual(row.count(" | "), 2)  # still exactly three cells

    def test_display_name_is_escaped(self):
        row = gpi.render_row(by_name(build(entries=[entry("Evil | Name")]), "Evil | Name"))
        self.assertIn("**Evil \\| Name**", row)

    def test_tables_have_three_columns_for_mobile(self):
        block = gpi.render_block(build([repo()], [entry()]))
        for line in block.splitlines():
            if line.startswith("| "):
                self.assertEqual(line.count(" | "), 2, line)
        self.assertEqual(gpi.TABLE_COLUMNS, ("Project", "What it does", "Role · Access"))

    def test_stack_moves_into_project_cell_and_is_escaped(self):
        p = by_name(build([repo(homepage="https://demo.example.com", topics=["status-live"])], overrides={"demo-app": {"stack": "Next.js · C# | Vite"}}), "demo-app")
        cell_text = gpi.render_row(p).split(" | ")[0]
        self.assertIn("<br><sub>Live · [Live](https://demo.example.com)</sub>", cell_text)
        self.assertIn("<br><sub>Stack: Next.js · C# \| Vite</sub>", cell_text)
        self.assertNotIn("Next.js", gpi.render_row(p).split(" | ")[1])

    def test_empty_stack_omits_stack_line(self):
        row = gpi.render_row(by_name(build(entries=[entry(stack="")]), "Private Thing"))
        self.assertNotIn("Stack:", row)

    def test_block_has_all_sections_and_markers(self):
        block = gpi.render_block(build([repo()], [entry()]))
        self.assertTrue(block.startswith(gpi.START_MARKER))
        self.assertTrue(block.endswith(gpi.END_MARKER))
        for heading in ("## Complete Project Portfolio", "## Private Products & Systems", "## Collaborative Work", "## Academic & Experiments"):
            self.assertIn(heading, block)

    def test_only_marker_region_changes(self):
        new = gpi.update_readme_text(README, build([repo()]))
        self.assertTrue(new.startswith("# Title\n\nintro\n\n" + gpi.START_MARKER))
        self.assertTrue(new.endswith(gpi.END_MARKER + "\n\n## Core Expertise\n"))

    def test_missing_markers_raises_and_readme_unchanged(self):
        with self.assertRaises(gpi.IndexError_):
            gpi.update_readme_text("# no markers", build([repo()]))

    def test_empty_result_keeps_existing_entries(self):
        filled = gpi.update_readme_text(README, build([repo()]))
        self.assertEqual(gpi.update_readme_text(filled, []), filled)


# --------------------------------------------------------------------------- footprint

class FootprintTests(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ROOT, "data", "footprint.json"), encoding="utf-8") as fh:
            self.data = json.load(fh)

    def test_footprint_file_is_valid(self):
        gpi.load_footprint(os.path.join(ROOT, "data", "footprint.json"))

    def test_svg_contains_exactly_the_measured_values(self):
        for theme in ("dark", "light"):
            svg = gpi.render_footprint_svg(self.data, theme)
            for m in self.data["metrics"]:
                self.assertIn(f'>{m["value"]:,}</text>', svg)
                self.assertIn(m["label"], svg)
            for lang in self.data["languages"]:
                self.assertIn(f'{lang["name"]} {lang["share"]:g}%', svg)
            self.assertIn(self.data["measured_on"], svg)
            self.assertTrue(svg.startswith("<svg ") and svg.rstrip().endswith("</svg>"))

    def test_committed_svgs_match_data(self):
        for theme, path in gpi.FOOTPRINT_SVG.items():
            with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
                self.assertEqual(fh.read(), gpi.render_footprint_svg(self.data, theme), path)

    def test_language_shares_sum_to_100(self):
        self.assertAlmostEqual(sum(l["share"] for l in self.data["languages"]), 100.0, places=1)

    def test_readme_alt_text_matches_data(self):
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
            readme = fh.read()
        for m in self.data["metrics"]:
            self.assertIn(str(m["value"]), readme)
        self.assertIn(self.data["measured_on"], readme)

    def test_invalid_footprint_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "f.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"metrics": [{"value": "many", "label": "x"}]}, fh)
            with self.assertRaises(gpi.IndexError_):
                gpi.load_footprint(path)


# --------------------------------------------------------------------------- repository data hygiene

FORBIDDEN = [
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),           # GitHub tokens
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),                    # OpenAI-style keys
    re.compile(r"AKIA[0-9A-Z]{16}"),                       # AWS
    re.compile(r"[A-Za-z]:\\\\?Users\\\\", re.I),        # Windows user paths
    re.compile(r"/c/Users/", re.I),
    re.compile(r"\.env\b"),
]
# SHA-256 prefixes of private repository / partner identifiers. Public files must not contain any token
# that hashes to one of these. The identifiers themselves are intentionally not stored in this repository.
PRIVATE_TOKEN_DIGESTS = {
    "1619e383d4aa9ffd",
    "1e4d113bbb6f1518",
    "290eac1e8ad3c97f",
    "3f77ea4c24bd6ea1",
    "443ca2057c0be89f",
    "4498cbd98590d3cd",
    "47e362d36e04685c",
    "4dc2b7e0b5de657c",
    "58fa4aa65502d0e8",
    "60c3538aefe9a570",
    "613c9fd3e9639e62",
    "68544ea1095ede00",
    "6efaf64744a24b1a",
    "7b92d3c4b3e02fa9",
    "7fb91b3162021716",
    "84e4f85cd8757c66",
    "904d09f555e5fa42",
    "91d31d619e148010",
    "92767a129a49d569",
    "ba043ed8a65bc8b6",
    "ba063cb5413a4264",
    "ba7e31178625b045",
    "bc6f7233ed387f0e",
    "c2df89e192db8300",
    "c6d5e52784139a6f",
    "c8454813f8daee10",
    "d129e5d80b43a5fd",
    "d1be17e3714f0935",
    "e0aceddffc46db08",
    "ec063ecd30d4f641",
    "fbf8c05d6f2fbf18",
}
_TOKEN = re.compile(r"[a-z0-9_\-]+")


def _digest(token: str) -> str:
    import hashlib
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


class HygieneTests(unittest.TestCase):
    PUBLIC_FILES = ["README.md", os.path.join("data", "project_catalog.json"), os.path.join("data", "footprint.json"),
                    os.path.join("generated", "projects.md"), os.path.join(".github", "workflows", "update-project-index.yml")]

    def _read(self, rel):
        with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
            return fh.read()

    def test_no_secrets_env_or_local_paths_in_public_files(self):
        for rel in self.PUBLIC_FILES:
            text = self._read(rel)
            for pat in FORBIDDEN:
                self.assertIsNone(pat.search(text), f"{rel}: {pat.pattern}")

    def test_no_private_repository_names_in_public_files(self):
        for rel in self.PUBLIC_FILES:
            for token in set(_TOKEN.findall(self._read(rel).lower())):
                self.assertNotIn(_digest(token), PRIVATE_TOKEN_DIGESTS, f"{rel} mentions a private identifier")

    def test_all_github_links_in_generated_block_point_to_public_owner_repos(self):
        text = self._read(os.path.join("generated", "projects.md"))
        for url in re.findall(r"\]\((https?://[^)]+)\)", text):
            if "github.com" in url:
                self.assertTrue(url.startswith(f"https://github.com/{OWNER}/"), url)

    def test_catalog_entries_have_no_urls_at_all_when_private(self):
        data = json.loads(self._read(os.path.join("data", "project_catalog.json")))
        for e in data["entries"]:
            if "Public" not in e["access"]:
                self.assertEqual(e.get("optional_public_url", ""), "", e["display_name"])
                for value in e.values():
                    self.assertNotIn("github.com", str(value), e["display_name"])


# --------------------------------------------------------------------------- fetch

class _Resp:
    def __init__(self, payload, status=200):
        self._b = json.dumps(payload).encode("utf-8")
        self.status = status

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FetchTests(unittest.TestCase):
    def test_pagination_is_followed(self):
        pages = [[repo(f"r{i}") for i in range(gpi.PER_PAGE)], [repo("last")]]
        seen = []

        def opener(req, timeout=None):
            seen.append(req.full_url)
            return _Resp(pages[len(seen) - 1])

        repos = gpi.fetch_public_repos(opener=opener)
        self.assertEqual(len(repos), gpi.PER_PAGE + 1)
        self.assertEqual(len(seen), 2)
        self.assertIn("page=1", seen[0])
        self.assertIn("page=2", seen[1])
        self.assertTrue(all(f"/users/{OWNER}/repos" in u for u in seen))

    def test_api_errors_raise_index_error(self):
        def http_error(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 503, "down", {}, None)

        def bad_payload(req, timeout=None):
            return _Resp({"message": "nope"})

        for opener in (http_error, bad_payload):
            with self.assertRaises(gpi.IndexError_):
                gpi.fetch_public_repos(opener=opener)

    def test_token_is_sent_but_never_logged(self):
        token = "ghp_" + "x" * 36
        captured = {}

        def opener(req, timeout=None):
            captured["auth"] = req.get_header("Authorization")
            raise urllib.error.HTTPError(req.full_url, 401, "bad", {}, None)

        old = os.environ.get("GITHUB_TOKEN")
        os.environ["GITHUB_TOKEN"] = token
        err = io.StringIO()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                readme = os.path.join(tmp, "README.md")
                with open(readme, "w", encoding="utf-8") as fh:
                    fh.write(README)
                real_open = gpi.urllib.request.urlopen
                gpi.urllib.request.urlopen = opener
                try:
                    sys.stderr, saved = err, sys.stderr
                    try:
                        rc = gpi.main(["--readme", readme, "--catalog", os.path.join(ROOT, "data", "project_catalog.json"), "--footprint", "", "--output", ""])
                    finally:
                        sys.stderr = saved
                finally:
                    gpi.urllib.request.urlopen = real_open
        finally:
            if old is None:
                del os.environ["GITHUB_TOKEN"]
            else:
                os.environ["GITHUB_TOKEN"] = old
        self.assertEqual(captured["auth"], f"Bearer {token}")
        self.assertEqual(rc, 1)
        self.assertNotIn(token, err.getvalue())


# --------------------------------------------------------------------------- main

class MainTests(unittest.TestCase):
    def _run(self, repos, readme_text=README, extra=()):
        with tempfile.TemporaryDirectory() as tmp:
            readme = os.path.join(tmp, "README.md")
            inp = os.path.join(tmp, "repos.json")
            cat = os.path.join(tmp, "catalog.json")
            out = os.path.join(tmp, "gen", "projects.md")
            with open(readme, "w", encoding="utf-8") as fh:
                fh.write(readme_text)
            with open(inp, "w", encoding="utf-8") as fh:
                json.dump(repos, fh)
            with open(cat, "w", encoding="utf-8") as fh:
                json.dump(catalog([entry()]), fh)
            args = ["--readme", readme, "--input", inp, "--catalog", cat, "--footprint", "", "--output", out, *extra]
            saved_out, saved_err = sys.stdout, sys.stderr
            sys.stdout, sys.stderr = io.StringIO(), io.StringIO()
            try:
                rc = gpi.main(args)
                rc2 = gpi.main(args)
                printed = sys.stdout.getvalue()
            finally:
                sys.stdout, sys.stderr = saved_out, saved_err
            with open(readme, encoding="utf-8") as fh:
                text = fh.read()
            gen = None
            if os.path.exists(out):
                with open(out, encoding="utf-8") as fh:
                    gen = fh.read()
            return rc, rc2, text, gen, printed

    def test_main_writes_index_and_second_run_changes_nothing(self):
        rc, rc2, text, gen, printed = self._run([repo()])
        self.assertEqual((rc, rc2), (0, 0))
        self.assertIn("[demo-app](", text)
        self.assertIn("**Private Thing**", text)
        self.assertTrue(gen.startswith(gpi.START_MARKER))
        self.assertIn("changed: nothing", printed.splitlines()[-1])

    def test_main_without_markers_fails_and_leaves_file(self):
        rc, _, text, gen, _ = self._run([repo()], readme_text="# nothing here\n")
        self.assertEqual(rc, 1)
        self.assertEqual(text, "# nothing here\n")
        self.assertIsNone(gen)

    def test_main_refuses_empty_api_result(self):
        rc, _, text, _, _ = self._run([])
        self.assertEqual(rc, 1)
        self.assertEqual(text, README)


if __name__ == "__main__":
    unittest.main()
