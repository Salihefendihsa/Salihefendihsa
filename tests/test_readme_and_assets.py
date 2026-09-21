"""Checks on the committed README.md and assets/v5 (what GitHub will actually render)."""
from __future__ import annotations

import json
import os
import re
import sys
import unittest
import xml.etree.ElementTree as ET

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import generate_portfolio as gp  # noqa: E402
import render_assets as ra  # noqa: E402

README_PATH = os.path.join(ROOT, "README.md")
SVG_NS = "{http://www.w3.org/2000/svg}"


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class ReadmeTests(unittest.TestCase):
    def setUp(self):
        self.readme = read(README_PATH)
        self.low = self.readme.lower()

    def test_mrc_commerce_has_zero_references(self):
        for variant in ("mrc-commerce", "mrc commerce", "mrccommerce", "mrc_commerce"):
            self.assertNotIn(variant, self.low)

    def test_flagship_names_are_present_and_correct(self):
        for i, name in enumerate(("Navlonix", "Nilüfer İlaçlama Operations Suite", "SALIH-AI-COMPANY"), 1):
            self.assertEqual(self.readme.count(f"Flagship {i:02d} — {name}:"), 1, name)
        self.assertNotIn("Multi-Agent AI Operations System", self.readme)
        self.assertNotIn("Field Service Operations Platform", self.readme)

    def test_section_order(self):
        order = ["assets/v5/hero-", "assets/v5/proof-", "How these numbers are measured",
                 "## 01 — Flagship Systems", "## 02 — Product Ecosystem", "assets/v5/ecosystem-",
                 "## 03 — Verified Collaborations", "assets/v5/collaborations-",
                 "## 04 — Engineering Method", "assets/v5/approach-", "## 05 — Complete Archive", "## Contact"]
        positions = [self.readme.index(s) for s in order]
        self.assertEqual(positions, sorted(positions))

    def test_collaborations_are_included_once_on_the_board(self):
        block = self.readme[self.readme.index("## 03 — Verified Collaborations"):self.readme.index("## 04 — Engineering Method")]
        alt = re.search(r'<img alt="([^"]+)" src="assets/v5/collaborations-desktop-light\.svg"', block).group(1)
        for name in ("Sticker &amp; Label Studio", "Couples Companion App", "Invitation Design Studio", "Product Photo Studio"):
            self.assertEqual(alt.count(name), 1, name)
        self.assertIn("Lead contributor, 71 / 75 commits", alt)
        self.assertIn("Core contributor, 37 commits · 36 PRs", alt)
        # the visible section is the board plus its intro line: no paragraphs repeating the cards
        visible = re.sub(r"<picture>.*?</picture>", "", block, flags=re.S)
        self.assertNotIn("Web studio for school name stickers", visible)
        self.assertEqual([l for l in visible.splitlines() if l.strip() and not l.startswith(("#", "<sub>", "<!--"))], [])

    def test_ecosystem_board_replaces_the_text_wall(self):
        block = self.readme[self.readme.index("## 02 — Product Ecosystem"):self.readme.index("## 03 — Verified Collaborations")]
        alt = re.search(r'<img alt="([^"]+)" src="assets/v5/ecosystem-desktop-light\.svg"', block).group(1)
        for name in ("Instagram AI Manager", "Finans Pro", "Tatlı Durağı POS &amp; QR Ordering", "AuraProject", "Nalbur Stok", "Optivark"):
            self.assertEqual(alt.count(name), 1, name)
        visible = re.sub(r"<picture>.*?</picture>", "", block, flags=re.S)
        self.assertNotIn("Multi-workspace backend", visible)
        self.assertNotIn("FIFO", visible)
        # only headings, <sub> lines and blank lines remain visible
        self.assertEqual([l for l in visible.splitlines() if l.strip() and not l.startswith(("#", "<sub>"))], [])

    def test_engineering_method_is_the_process_diagram(self):
        block = self.readme[self.readme.index("## 04 — Engineering Method"):self.readme.index("## 05 — Complete Archive")]
        self.assertIn("assets/v5/approach-mobile-dark.svg", block)
        self.assertNotIn("- **", block)  # the old bullet list is gone
        alt = re.search(r'<img alt="([^"]+)"', block).group(1)
        for stage in ("Architecture", "Typed Boundaries", "Testable Workflows", "Human Approval", "Observe and Improve"):
            self.assertIn(stage, alt)

    def test_responsive_pictures_have_ordered_sources(self):
        for base in ("hero", "proof", "ecosystem", "collaborations", "approach"):
            start = self.readme.index(f"assets/v5/{base}-mobile-dark.svg")
            pic = re.search(r"<picture>\s*(.*?)\s*</picture>", self.readme[self.readme.rfind("<picture>", 0, start):], re.S)
            self.assertIsNotNone(pic, base)
            lines = [l.strip() for l in pic.group(1).splitlines()]
            expected = [
                f'<source media="(prefers-color-scheme: dark) and (max-width: 600px)" srcset="assets/v5/{base}-mobile-dark.svg">',
                f'<source media="(max-width: 600px)" srcset="assets/v5/{base}-mobile-light.svg">',
                f'<source media="(prefers-color-scheme: dark)" srcset="assets/v5/{base}-desktop-dark.svg">',
            ]
            self.assertEqual(lines[:3], expected, base)
            self.assertRegex(lines[3], rf'^<img alt="[^"]{{20,}}" src="assets/v5/{base}-desktop-light\.svg" width="100%">$')

    def test_full_descriptions_live_only_in_the_collapsed_archive(self):
        archive = self.readme[self.readme.index("## 05 — Complete Archive"):]
        self.assertIn("<summary><b>Selected products — full descriptions</b> (10)</summary>", archive)
        before = self.readme[:self.readme.index("## 05 — Complete Archive")]
        self.assertNotIn("Multi-workspace backend", before)
        self.assertEqual(archive.count("Template library, positioned text editor"), 1)

    def test_no_private_or_foreign_github_urls(self):
        with open(os.path.join(ROOT, "data", "portfolio.json"), encoding="utf-8") as fh:
            pf = json.load(fh)
        public = {m.group(1).lower() for m in re.finditer(r"https://github\.com/" + gp.OWNER + r"/([A-Za-z0-9_.-]+)", self.readme)}
        # every linked repository must be a claimed public source or an archive override (public by construction)
        claimed = {s["repo"].split("/")[1].lower() for p in pf["products"] for s in p["repository_sources"] if s["kind"] == "public"}
        overrides = {k.lower() for k in pf["archive_overrides"] if not k.startswith("$")}
        for name in public:
            self.assertIn(name, claimed | overrides, name)
        gp.check_generated_text(self.readme, pf, public)
        for private in ("yuk-le", "nilufer-yonetim", "talhamercan", "instagram-ai-manager", "finans-pro-backend",
                        "optivark-web", "etiketuygulamasi", "sevgilitrip", "davetiye", "aipostyaptirma"):
            self.assertNotIn(private, self.low, private)

    def test_no_credentials_or_internal_paths(self):
        for pattern in (r"gh[pous]_[A-Za-z0-9]{20,}", r"github_pat_", r"[A-Z]:\\\\", r"/home/\w+", r"C:/Users", r"AKIA[0-9A-Z]{16}"):
            self.assertIsNone(re.search(pattern, self.readme), pattern)

    def test_every_relative_asset_exists_with_exact_case(self):
        refs = set(re.findall(r'(?:src|srcset)="([^"]+)"', self.readme))
        self.assertTrue(refs)
        for ref in refs:
            self.assertFalse(ref.startswith(("http://", "https://")), ref)
            path = os.path.join(ROOT, *ref.split("/"))
            self.assertTrue(os.path.isfile(path), ref)
            directory, name = os.path.split(path)
            self.assertIn(name, os.listdir(directory), f"case mismatch: {ref}")

    def test_pictures_have_light_dark_and_fallback(self):
        pictures = re.findall(r"<picture>(.*?)</picture>", self.readme, re.S)
        self.assertEqual(len(pictures), 8)
        for pic in pictures:
            self.assertIn('media="(prefers-color-scheme: dark)"', pic)
            self.assertRegex(pic, r'<img alt="[^"]{10,}" src="assets/v5/[^"]+-light\.svg" width="100%">')
            for src in re.findall(r'srcset="([^"]+)"', pic):
                self.assertTrue(src.endswith(("-dark.svg", "-light.svg")), src)

    def test_details_blocks_are_balanced(self):
        self.assertEqual(self.readme.count("<details>"), self.readme.count("</details>"))
        self.assertEqual(self.readme.count("<summary>"), self.readme.count("</summary>"))
        self.assertGreaterEqual(self.readme.count("<details>"), 3)

    def test_generated_blocks_match_generated_files(self):
        s, e = gp.find_block(self.readme, gp.PORTFOLIO_START, gp.PORTFOLIO_END)
        self.assertEqual(self.readme[s:e] + "\n", read(os.path.join(ROOT, "generated", "portfolio.md")))
        s, e = gp.find_block(self.readme, gp.ARCHIVE_START, gp.ARCHIVE_END)
        self.assertEqual(self.readme[s:e] + "\n", read(os.path.join(ROOT, "generated", "project-archive.md")))

    def test_proof_strip_numbers_match_footprint(self):
        with open(os.path.join(ROOT, "data", "footprint.json"), encoding="utf-8") as fh:
            fp = json.load(fh)
        for m in fp["metrics"]:
            self.assertIn(f"{m['value']:,}", self.readme)
        self.assertIn("How these numbers are measured", self.readme)
        self.assertIn("not GitHub's contribution count", self.readme)

    def test_no_unbreakable_words_for_mobile(self):
        self.assertLessEqual(gp.longest_word(self.readme), 34)

    def test_story_before_archive(self):
        archive = self.readme.index("## 05 — Complete Archive")
        for s in ("Flagship 01 — Navlonix:", "## 02 — Product Ecosystem", "## 03 — Verified Collaborations", "## 04 — Engineering Method"):
            self.assertLess(self.readme.index(s), archive)


class AssetTests(unittest.TestCase):
    def setUp(self):
        self.dir = os.path.join(ROOT, "assets", "v5")
        self.files = sorted(f for f in os.listdir(self.dir) if f.endswith(".svg"))

    def test_expected_asset_set(self):
        names = [f"{r}-{bp}" for r in ra.RESPONSIVE_ASSETS for bp in ("desktop", "mobile")] + [f"flagship-{pid}" for pid in ra.FLAGSHIPS]
        expected = {f"{n}-{t}.svg" for t in ("light", "dark") for n in names}
        self.assertEqual(set(self.files), expected)
        self.assertEqual(len(self.files), 26)

    def test_mobile_geometry_is_recomposed_not_scaled(self):
        for r in ra.RESPONSIVE_ASSETS:
            d = ET.fromstring(read(os.path.join(self.dir, f"{r}-desktop-light.svg")))
            m = ET.fromstring(read(os.path.join(self.dir, f"{r}-mobile-light.svg")))
            self.assertEqual(d.get("width"), "1200", r)
            self.assertEqual(m.get("width"), "720", r)
            dw, dh = (float(v) for v in d.get("viewBox").split()[2:])
            mw, mh = (float(v) for v in m.get("viewBox").split()[2:])
            self.assertGreater(mh / mw, dh / dw, f"{r}: mobile must be taller in proportion")
            dtext = {(el.text or "") for el in d.iter(f"{SVG_NS}text")}
            mtext = {(el.text or "") for el in m.iter(f"{SVG_NS}text")}
            self.assertTrue(dtext & mtext, r)  # same story ...
            dpos = [(el.get("x"), el.get("y")) for el in d.iter(f"{SVG_NS}text")]
            mpos = [(el.get("x"), el.get("y")) for el in m.iter(f"{SVG_NS}text")]
            self.assertNotEqual(dpos, mpos, r)  # ... different composition

    def test_boards_contain_every_product_and_stage(self):
        eco = read(os.path.join(self.dir, "ecosystem-desktop-light.svg"))
        for name in ("Instagram AI Manager", "Finans Pro", "Tatlı Durağı POS &amp; QR Ordering", "AuraProject", "Nalbur Stok", "Optivark"):
            self.assertEqual(eco.count(f">{name}<"), 1, name)
        col = read(os.path.join(self.dir, "collaborations-desktop-light.svg"))
        for name, evidence in (("Sticker &amp; Label Studio", "71 / 75 commits"), ("Couples Companion App", "37 commits · 36 PRs"),
                               ("Invitation Design Studio", "5 / 6 commits"), ("Product Photo Studio", "2 / 7 commits")):
            self.assertEqual(col.count(f">{name}<"), 1, name)
            self.assertIn(f">{evidence}<", col)
        app = read(os.path.join(self.dir, "approach-mobile-dark.svg"))
        for stage in ("Architecture", "Typed Boundaries", "Testable Workflows", "Human Approval", "Observe &amp; Improve"):
            self.assertIn(f">{stage}<", app)
        for name in self.files:
            self.assertNotIn("mrc", read(os.path.join(self.dir, name)).lower(), name)

    def test_svgs_are_valid_xml_with_title_and_no_external_resources(self):
        for name in self.files:
            svg = read(os.path.join(self.dir, name))
            root = ET.fromstring(svg)
            self.assertEqual(root.tag, f"{SVG_NS}svg", name)
            self.assertIsNotNone(root.find(f"{SVG_NS}title"), name)
            self.assertTrue(root.find(f"{SVG_NS}title").text.strip(), name)
            self.assertEqual(root.get("role"), "img")
            low = svg.lower()
            for banned in ("<script", "http://", "https://", "@import", "url(", "<filter", "<animate", "<image", "<foreignobject", "onload"):
                if banned == "http://":
                    self.assertEqual(low.count("http://"), low.count("http://www.w3.org/2000/svg"), name)
                    continue
                self.assertNotIn(banned, low, f"{banned} in {name}")

    def test_light_and_dark_geometry_match(self):
        for name in self.files:
            if name.endswith("-light.svg"):
                light = ET.fromstring(read(os.path.join(self.dir, name)))
                dark = ET.fromstring(read(os.path.join(self.dir, name.replace("-light", "-dark"))))
                geo = lambda root: [(el.tag, {k: v for k, v in el.attrib.items() if k not in ("fill", "stroke")}, (el.text or "").strip())
                                    for el in root.iter()]
                self.assertEqual(geo(light), geo(dark), name)
                self.assertEqual(light.get("viewBox"), dark.get("viewBox"))

    def test_text_sizes_are_readable_after_github_scaling(self):
        # Mobile assets (720 px) render at ~350 px: every glyph >= 17 px (~8 px rendered), primary type >= 34 px.
        # Desktop assets (1200 px) render at ~900 px on desktop: every glyph >= 15 px.
        for name in self.files:
            root = ET.fromstring(read(os.path.join(self.dir, name)))
            sizes = [float(t.get("font-size")) for t in root.iter(f"{SVG_NS}text")]
            self.assertTrue(sizes, name)
            if "-mobile-" in name:
                self.assertGreaterEqual(min(sizes), 17, name)
                self.assertGreaterEqual(max(sizes), 30, name)
            else:
                self.assertGreaterEqual(min(sizes), 15, name)
                self.assertGreaterEqual(max(sizes), 23, name)
            if name.startswith(("hero-", "proof-", "flagship-")):
                self.assertGreaterEqual(max(sizes), 46, name)

    def test_system_fonts_only(self):
        for name in self.files:
            svg = read(os.path.join(self.dir, name))
            for fam in set(re.findall(r'font-family="([^"]+)"', svg)):
                self.assertIn(fam, (ra.SANS, ra.MONO), name)

    def test_assets_are_reproducible_from_the_renderer(self):
        with open(os.path.join(ROOT, "data", "footprint.json"), encoding="utf-8") as fh:
            fp = json.load(fh)
        with open(os.path.join(ROOT, "data", "portfolio.json"), encoding="utf-8") as fh:
            pf = json.load(fh)
        for rel, content in ra.render_all(fp, pf).items():
            self.assertEqual(read(os.path.join(ROOT, rel)), content, rel)

    def test_proof_cards_are_data_driven(self):
        fp = {"measured_on": "2026-01-01", "window": {"label": "W", "from": "2025-01-01", "to": "2026-01-01"},
              "metrics": [{"key": "a", "value": 1234, "label": "Alpha things", "note": "n"}, {"key": "b", "value": 5, "label": "Beta"}]}
        for mobile in (False, True):
            svg = ra.render_proof(fp, "light", mobile=mobile)
            self.assertIn("1,234", svg)
            self.assertIn("Alpha things", svg)
            self.assertIn("JAN 2025", svg)
            self.assertNotIn("%", svg)  # no language-percentage dashboard, no progress bars
            ET.fromstring(svg)

    def test_broken_relative_asset_is_detected(self):
        readme = read(README_PATH) + ' src="assets/v5/missing-desktop-light.svg"'
        refs = set(re.findall(r'(?:src|srcset)="([^"]+)"', readme))
        missing = [r for r in refs if not os.path.isfile(os.path.join(ROOT, *r.split("/")))]
        self.assertEqual(missing, ["assets/v5/missing-desktop-light.svg"])


if __name__ == "__main__":
    unittest.main()
