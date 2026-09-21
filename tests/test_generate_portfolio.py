"""Tests for scripts/generate_portfolio.py (standard library only)."""
from __future__ import annotations

import copy
import io
import json
import os
import re
import sys
import tempfile
import unittest
import urllib.error
import xml.etree.ElementTree as ET

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import generate_portfolio as gp  # noqa: E402

OWNER = gp.OWNER


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
        "size": 120,
        "pushed_at": "2026-05-01T00:00:00Z",
        "topics": [],
    }
    base.update(over)
    return base


def product(pid="thing", tier=2, **over):
    base = {
        "product_id": pid,
        "display_name": pid.replace("-", " ").title(),
        "tagline": "Does a thing.",
        "summary": "Does a private thing well.",
        "role": "Solo engineer",
        "status": "In development",
        "access": "Private",
        "category": "Tools",
        "repository_sources": [{"kind": "private", "label": "Backend"}],
        "public_links": [],
        "stack": ["Python"],
        "featured_tier": tier,
        "publish_name": True,
        "publish_repository_links": False,
        "collaboration": None,
        "sort_order": 10,
    }
    if tier == 1:
        base.update({"problem": "A problem.", "built": ["One", "Two"], "surfaces": ["API", "Web"], "visual": pid})
    base.update(over)
    return base


def portfolio(products=None, overrides=None, private_entries=None, excluded=("mrc-commerce",)):
    return {
        "version": 5,
        "profile_excluded_repositories": list(excluded),
        "products": products or [],
        "archive_groups": ["Tools & Research", "University Coursework"],
        "archive_overrides": overrides or {},
        "private_archive_entries": {"entries": private_entries or []},
    }


README = "# Hi\n\n<!-- PORTFOLIO:START -->\nold\n<!-- PORTFOLIO:END -->\n\ntext\n\n<!-- ARCHIVE:START -->\nold\n<!-- ARCHIVE:END -->\n\nbye\n"


def generate(repos, pf):
    products, archive = gp.build(repos, pf)
    return gp.update_readme_text(README, products, archive, gp.archive_groups(pf))


# --------------------------------------------------------------------------- exclusion

class ExclusionTests(unittest.TestCase):
    def test_mrc_commerce_is_excluded_from_discovery(self):
        pf = portfolio()
        repos = [repo("mrc-commerce", description="Storefront"), repo("MRC-Commerce"), repo("other")]
        text = generate(repos, pf)
        self.assertNotIn("mrc", text.lower())
        self.assertIn("other", text)

    def test_excluded_repository_cannot_be_claimed_by_a_product(self):
        pf = portfolio([product("shop", repository_sources=[{"kind": "public", "repo": f"{OWNER}/mrc-commerce"}])])
        with self.assertRaises(gp.PortfolioError):
            gp.validate_portfolio(pf)

    def test_excluded_repository_cannot_have_an_archive_override(self):
        pf = portfolio(overrides={"mrc-commerce": {"display_name": "MRC"}})
        with self.assertRaises(gp.PortfolioError):
            gp.validate_portfolio(pf)

    def test_generated_text_check_refuses_excluded_name_variants(self):
        pf = portfolio()
        for text in ("see mrc-commerce", "MRC Commerce storefront", "mrccommerce"):
            with self.assertRaises(gp.PortfolioError):
                gp.check_generated_text(text, pf, set())

    def test_profile_repository_is_excluded(self):
        text = generate([repo(OWNER, description="Config files"), repo("keep")], portfolio())
        self.assertNotIn(f"https://github.com/{OWNER}/{OWNER}", text)
        self.assertIn("keep", text)

    def test_forks_private_disabled_hidden_and_empty_are_skipped(self):
        pf = portfolio()
        for bad in (repo("f", fork=True), repo("p", private=True, visibility="private"), repo("d", disabled=True),
                    repo("h", topics=["profile-hide"]), repo("e", size=0, language=None),
                    repo("o", owner={"login": "someone-else"})):
            self.assertFalse(gp.is_listed(bad, pf), bad["name"])
        self.assertTrue(gp.is_listed(repo("ok"), pf))


# --------------------------------------------------------------------------- grouping

class GroupingTests(unittest.TestCase):
    def test_public_repository_claimed_by_a_product_appears_once(self):
        pf = portfolio([product("aura", repository_sources=[{"kind": "public", "repo": f"{OWNER}/aura-service"}],
                                publish_repository_links=True)])
        text = generate([repo("aura-service"), repo("tool")], pf)
        self.assertEqual(text.count(f"https://github.com/{OWNER}/aura-service"), 1)
        # the archive must not repeat it
        archive = text[text.index(gp.ARCHIVE_START):]
        self.assertNotIn("aura-service", archive)
        self.assertIn("tool", archive)

    def test_frontend_and_backend_repositories_are_one_product(self):
        pf = portfolio([product("finans", repository_sources=[
            {"kind": "public", "repo": f"{OWNER}/finans-api"}, {"kind": "public", "repo": f"{OWNER}/finans-app"}],
            publish_repository_links=True)])
        products, archive = gp.build([repo("finans-api"), repo("finans-app")], pf)
        self.assertEqual(len(products), 1)
        self.assertEqual(archive, [])
        self.assertEqual(len(products[0].repo_urls), 2)

    def test_a_repository_cannot_belong_to_two_products(self):
        src = [{"kind": "public", "repo": f"{OWNER}/x"}]
        pf = portfolio([product("a", repository_sources=src), product("b", repository_sources=src)])
        with self.assertRaises(gp.PortfolioError):
            gp.build([repo("x")], pf)

    def test_product_referencing_unlisted_repository_fails_closed(self):
        pf = portfolio([product("a", repository_sources=[{"kind": "public", "repo": f"{OWNER}/gone"}])])
        with self.assertRaises(gp.PortfolioError):
            gp.build([repo("other")], pf)

    def test_every_project_appears_exactly_once(self):
        pf = portfolio(
            [product("nav", tier=1), product("eco"), product("collab", collaboration={"label": "Built in collaboration", "evidence": "5 of 6 commits"}),
             product("pub", repository_sources=[{"kind": "public", "repo": f"{OWNER}/pub-repo"}], publish_repository_links=True)],
            overrides={"lab1": {"display_name": "OOP Lab 1", "group": "University Coursework"}},
            private_entries=[{"display_name": "OOP Lab — Private", "summary": "x", "group": "University Coursework", "access": "Private"}],
        )
        repos = [repo("pub-repo"), repo("lab1"), repo("tool")]
        products, archive = gp.build(repos, pf)
        names = [p.name for p in products] + [a.name for a in archive]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(names), 4 + 3)
        text = re.sub(r"https?://\S+", "", generate(repos, pf))
        for name in ("Eco", "Collab", "Pub", "OOP Lab 1", "OOP Lab — Private", "tool"):
            self.assertEqual(len(re.findall(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text)), 1, name)
        self.assertEqual(text.count("### Nav" + chr(10)), 1)  # flagship: one heading (+ its own image alt text)

    def test_duplicate_display_names_are_rejected(self):
        pf = portfolio([product("a", display_name="Same"), product("b", display_name="same")])
        with self.assertRaises(gp.PortfolioError):
            gp.validate_portfolio(pf)


# --------------------------------------------------------------------------- classification

class ClassificationTests(unittest.TestCase):
    def test_archived_fork_and_coursework_classification(self):
        pf = portfolio(overrides={"Lab-2": {"group": "University Coursework"}})
        groups = gp.archive_groups(pf)
        ov = gp.archive_overrides(pf)
        self.assertEqual(gp.archive_entry_from_repo(repo("old", archived=True), ov, groups).group, "Earlier Work")
        self.assertEqual(gp.archive_entry_from_repo(repo("hw", topics=["coursework"]), ov, groups).group, "University Coursework")
        self.assertEqual(gp.archive_entry_from_repo(repo("Lab-2"), ov, groups).group, "University Coursework")
        self.assertEqual(gp.archive_entry_from_repo(repo("tool"), ov, groups).group, "Tools & Research")
        self.assertFalse(gp.is_listed(repo("fork", fork=True), pf))

    def test_coursework_is_collapsed_and_after_tools(self):
        pf = portfolio(overrides={"hw": {"group": "University Coursework"}})
        text = generate([repo("hw"), repo("tool")], pf)
        archive = text[text.index(gp.ARCHIVE_START):]
        self.assertLess(archive.index("Tools &amp; Research"), archive.index("University Coursework"))
        self.assertIn("<details>", archive)
        self.assertEqual(archive.count("<details>"), archive.count("</details>"))

    def test_unexpected_repository_url_is_refused(self):
        pf = portfolio()
        with self.assertRaises(gp.PortfolioError):
            gp.archive_entry_from_repo(repo("x", html_url="https://evil.example/x"), {}, gp.archive_groups(pf))


# --------------------------------------------------------------------------- privacy

class PrivacyTests(unittest.TestCase):
    def test_private_source_must_be_opaque(self):
        for src in ({"kind": "private", "label": f"{OWNER}/secret"}, {"kind": "private", "label": "github.com/x"},
                    {"kind": "collaboration", "label": "Partner", "repo": "talha/secret"}):
            pf = portfolio([product("p", repository_sources=[src])])
            with self.assertRaises(gp.PortfolioError, msg=src):
                gp.validate_portfolio(pf)

    def test_public_source_must_be_owned(self):
        pf = portfolio([product("p", repository_sources=[{"kind": "public", "repo": "someone/else"}])])
        with self.assertRaises(gp.PortfolioError):
            gp.validate_portfolio(pf)

    def test_public_links_never_point_at_github(self):
        pf = portfolio([product("p", public_links=[{"label": "Repo", "url": f"https://github.com/{OWNER}/secret"}])])
        with self.assertRaises(gp.PortfolioError):
            gp.validate_portfolio(pf)

    def test_repository_links_need_a_public_source(self):
        pf = portfolio([product("p", publish_repository_links=True)])
        with self.assertRaises(gp.PortfolioError):
            gp.validate_portfolio(pf)

    def test_collaboration_cannot_claim_owned_public_repository(self):
        pf = portfolio([product("p", collaboration={"label": "Built in collaboration", "evidence": "1 of 2"},
                                repository_sources=[{"kind": "public", "repo": f"{OWNER}/x"}])])
        with self.assertRaises(gp.PortfolioError):
            gp.validate_portfolio(pf)

    def test_generated_text_rejects_unlisted_github_urls(self):
        pf = portfolio()
        gp.check_generated_text(f"[x](https://github.com/{OWNER}/listed) [me](https://github.com/{OWNER})", pf, {"listed"})
        for bad in (f"https://github.com/{OWNER}/private-one", "https://github.com/talha/secret", f"https://gist.github.com/{OWNER}/1"):
            with self.assertRaises(gp.PortfolioError, msg=bad):
                gp.check_generated_text(f"see {bad}", pf, {"listed"})

    def test_private_archive_entries_cannot_reference_repositories(self):
        pf = portfolio(private_entries=[{"display_name": "x/y", "summary": "s", "group": "University Coursework"}])
        with self.assertRaises(gp.PortfolioError):
            gp.validate_portfolio(pf)
        pf = portfolio(private_entries=[{"display_name": "Lab", "summary": "see github.com/a/b", "group": "University Coursework"}])
        with self.assertRaises(gp.PortfolioError):
            gp.validate_portfolio(pf)

    def test_no_private_product_gets_a_repository_link(self):
        pf = portfolio([product("p", access="Private")])
        text = generate([repo("tool")], pf)
        block = text[text.index(gp.PORTFOLIO_START):text.index(gp.PORTFOLIO_END)]
        self.assertNotIn("github.com", block)


# --------------------------------------------------------------------------- collaboration labelling

class CollaborationTests(unittest.TestCase):
    def test_collaboration_is_labelled_without_implying_ownership(self):
        pf = portfolio([product("stud", display_name="Sticker Studio", role="Lead contributor", access="Partner-owned · private",
                                collaboration={"label": "Built in collaboration", "evidence": "71 of 75 commits"})])
        text = generate([repo("tool")], pf)
        collab = text[text.index("## Selected Collaborations"):text.index(gp.PORTFOLIO_END)]
        self.assertIn("Sticker Studio", collab)
        self.assertIn("Built in collaboration · Lead contributor · 71 of 75 commits", collab)
        self.assertIn("Partner-owned · private", collab)
        eco = text[text.index("## Selected Product Ecosystem"):text.index("## Selected Collaborations")]
        self.assertNotIn("Sticker Studio", eco)

    def test_collaboration_needs_label_and_evidence(self):
        pf = portfolio([product("p", collaboration={"label": "Built in collaboration"})])
        with self.assertRaises(gp.PortfolioError):
            gp.validate_portfolio(pf)


# --------------------------------------------------------------------------- determinism / idempotency

class DeterminismTests(unittest.TestCase):
    def test_order_is_deterministic_regardless_of_input_order(self):
        pf = portfolio([product("b", sort_order=20), product("a", sort_order=10), product("z", tier=1)])
        repos = [repo("zeta"), repo("alpha"), repo("Beta")]
        t1 = generate(repos, pf)
        pf2 = copy.deepcopy(pf)
        pf2["products"].reverse()
        t2 = generate(list(reversed(repos)), pf2)
        self.assertEqual(t1, t2)
        products, archive = gp.build(repos, pf)
        self.assertEqual([p.product_id for p in products], ["z", "a", "b"])
        self.assertEqual([a.name for a in archive], ["alpha", "Beta", "zeta"])

    def test_pushed_at_does_not_change_output(self):
        pf = portfolio()
        t1 = generate([repo("a", pushed_at="2026-01-01T00:00:00Z"), repo("b", pushed_at="2026-02-01T00:00:00Z")], pf)
        t2 = generate([repo("a", pushed_at="2026-03-01T00:00:00Z"), repo("b", pushed_at="2025-02-01T00:00:00Z")], pf)
        self.assertEqual(t1, t2)

    def test_generation_is_idempotent(self):
        pf = portfolio([product("p", tier=1), product("q")])
        repos = [repo("tool")]
        products, archive = gp.build(repos, pf)
        groups = gp.archive_groups(pf)
        once = gp.update_readme_text(README, products, archive, groups)
        twice = gp.update_readme_text(once, products, archive, groups)
        self.assertEqual(once, twice)
        self.assertTrue(once.startswith("# Hi\n\n"))
        self.assertTrue(once.endswith("\n\nbye\n"))
        self.assertIn("\n\ntext\n\n", once)

    def test_missing_markers_refuse_to_modify(self):
        with self.assertRaises(gp.PortfolioError):
            gp.find_block("no markers here", gp.PORTFOLIO_START, gp.PORTFOLIO_END)


# --------------------------------------------------------------------------- escaping / mobile safety

class RenderingTests(unittest.TestCase):
    def test_markdown_is_escaped(self):
        pf = portfolio()
        r = repo("weird", description="a | b [c](d) *e* <img src=x> `f` #g")
        text = generate([r], pf)
        row = [l for l in text.splitlines() if "weird" in l][0]
        self.assertIn("a \\| b \\[c\\](d) \\*e\\* \\<img src=x\\> \\`f\\` \\#g", row)
        self.assertEqual(row.count("|") - row.count("\\|"), 3)

    def test_generated_content_has_no_unbreakable_long_words(self):
        pf = portfolio([product("p", tier=1)])
        text = generate([repo("tool")], pf)
        self.assertLessEqual(gp.longest_word(text), 30)
        self.assertGreater(gp.longest_word("x " + "a" * 40), 30)

    def test_flagship_uses_light_and_dark_assets_with_fallback(self):
        pf = portfolio([product("nav", tier=1, visual="navlonix")])
        text = generate([repo("tool")], pf)
        self.assertIn('srcset="assets/v5/flagship-navlonix-dark.svg"', text)
        self.assertIn('srcset="assets/v5/flagship-navlonix-light.svg"', text)
        self.assertIn('<img alt="', text)
        self.assertIn('src="assets/v5/flagship-navlonix-light.svg" width="100%"', text)

    def test_flagship_bullets_are_capped(self):
        pf = portfolio([product("nav", tier=1, built=["1", "2", "3", "4", "5"])])
        with self.assertRaises(gp.PortfolioError):
            gp.validate_portfolio(pf)

    def test_at_most_three_flagships(self):
        pf = portfolio([product(f"f{i}", tier=1) for i in range(4)])
        with self.assertRaises(gp.PortfolioError):
            gp.validate_portfolio(pf)

    def test_meta_lines_are_single_source_lines(self):
        # GitHub turns a line-ending <br> into a double break; every <sub> block must stay on one line.
        pf = portfolio([product("nav", tier=1), product("eco")])
        text = generate([repo("tool")], pf)
        for line in text.splitlines():
            self.assertFalse(line.endswith("<br>"), line)

    def test_archive_table_is_two_columns(self):
        text = generate([repo("tool")], portfolio())
        rows = [l for l in text.splitlines() if l.startswith("| ")]
        for row in rows:
            self.assertEqual(row.count("|") - row.count("\\|"), 3, row)


# --------------------------------------------------------------------------- API behaviour

class _Resp:
    def __init__(self, payload, status=200):
        self._body = json.dumps(payload).encode("utf-8")
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class ApiTests(unittest.TestCase):
    def test_pagination_is_followed(self):
        pages = [[repo(f"r{i}") for i in range(gp.PER_PAGE)], [repo("last")]]
        calls = []

        def opener(req, timeout=0):
            calls.append(req.full_url)
            return _Resp(pages[len(calls) - 1])

        repos = gp.fetch_public_repos(opener=opener)
        self.assertEqual(len(repos), gp.PER_PAGE + 1)
        self.assertEqual(len(calls), 2)
        self.assertIn("page=2", calls[1])

    def test_http_error_is_a_portfolio_error(self):
        def opener(req, timeout=0):
            raise urllib.error.HTTPError(req.full_url, 503, "down", {}, io.BytesIO(b""))
        with self.assertRaises(gp.PortfolioError):
            gp.fetch_public_repos(opener=opener)

    def test_bad_payload_is_a_portfolio_error(self):
        with self.assertRaises(gp.PortfolioError):
            gp.fetch_public_repos(opener=lambda req, timeout=0: _Resp({"message": "nope"}))

    def test_token_is_sent_but_never_printed(self):
        seen = {}

        def opener(req, timeout=0):
            seen["auth"] = req.get_header("Authorization")
            return _Resp([])

        old = os.environ.get("GITHUB_TOKEN")
        os.environ["GITHUB_TOKEN"] = "ghp_secret"
        try:
            gp.fetch_public_repos(opener=opener)
        finally:
            if old is None:
                del os.environ["GITHUB_TOKEN"]
            else:
                os.environ["GITHUB_TOKEN"] = old
        self.assertEqual(seen["auth"], "Bearer ghp_secret")

    def test_empty_api_response_leaves_readme_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            readme = os.path.join(tmp, "README.md")
            with open(readme, "w", encoding="utf-8") as fh:
                fh.write(README)
            pf = os.path.join(tmp, "portfolio.json")
            with open(pf, "w", encoding="utf-8") as fh:
                json.dump(portfolio([product("p")]), fh)
            empty = os.path.join(tmp, "repos.json")
            with open(empty, "w", encoding="utf-8") as fh:
                json.dump([], fh)
            stderr, sys.stderr = sys.stderr, io.StringIO()
            try:
                code = gp.main(["--readme", readme, "--portfolio", pf, "--footprint", "", "--input", empty,
                                "--out-portfolio", "", "--out-archive", ""])
            finally:
                sys.stderr = stderr
            self.assertEqual(code, 1)
            with open(readme, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), README)


# --------------------------------------------------------------------------- end-to-end with the real data

class RealDataTests(unittest.TestCase):
    """The committed portfolio must be valid and safe against a representative repository list."""

    def setUp(self):
        with open(os.path.join(ROOT, "data", "portfolio.json"), encoding="utf-8") as fh:
            self.pf = json.load(fh)

    def test_committed_portfolio_is_valid(self):
        gp.validate_portfolio(self.pf)
        self.assertIn("mrc-commerce", self.pf["profile_excluded_repositories"])
        names = {p["display_name"] for p in self.pf["products"]}
        for required in ("Navlonix", "Nilüfer İlaçlama Operations Suite", "SALIH-AI-COMPANY"):
            self.assertIn(required, names)
        self.assertEqual(sum(1 for p in self.pf["products"] if p["featured_tier"] == 1), 3)
        self.assertEqual(sum(1 for p in self.pf["products"] if p.get("collaboration")), 4)

    def test_committed_portfolio_contains_no_private_repository_names(self):
        text = json.dumps(self.pf, ensure_ascii=False).lower()
        # product ids are slugs of public product names; these are repository names that must never be written
        for private in ("yuk-le", "nilufer-yonetim", "finans-pro-backend", "finans-pro-app", "tatliduragi",
                        "tatli-duragi-adisyon", "optivark-web", "etiketuygulamasi", "sevgilitrip", "davetiye",
                        "aipostyaptirma", "talhamercan", "github.com", "vercel.app"):
            self.assertNotIn(private, text, private)

    def test_generation_with_public_repositories_including_mrc(self):
        repos = [repo("mrc-commerce", description="Cinematic storefront", homepage="https://mrc-commerce.vercel.app"),
                 repo("nalbur-stok"), repo("auraproject-ai-service", language="Python"), repo("LLMChatbot", language="C#"),
                 repo(OWNER, description="Config files for my GitHub profile."), repo("web-lab-1", size=0, language=None),
                 repo("NTP_Lab", language="C#")]
        text = generate(repos, self.pf)
        self.assertNotIn("mrc", text.lower())
        self.assertNotIn("vercel.app/mrc", text)
        listed = {r["name"].lower() for r in repos if gp.is_listed(r, self.pf)}
        gp.check_generated_text(text, self.pf, listed)
        self.assertIn("### Navlonix", text)
        self.assertIn("### Nilüfer İlaçlama Operations Suite", text)
        self.assertIn("### SALIH-AI-COMPANY", text)
        self.assertNotIn("Web Lab 1", text)
        self.assertLessEqual(gp.longest_word(text), 30)


if __name__ == "__main__":
    unittest.main()
