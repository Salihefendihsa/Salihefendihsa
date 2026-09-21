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
        self.assertIn("### Navlonix", self.readme)
        self.assertIn("### Nilüfer İlaçlama Operations Suite", self.readme)
        self.assertIn("### SALIH-AI-COMPANY", self.readme)
        self.assertNotIn("Multi-Agent AI Operations System", self.readme)
        self.assertNotIn("Field Service Operations Platform", self.readme)

    def test_section_order(self):
        order = ["assets/v5/hero-", "assets/v5/proof-strip-", "How these numbers are measured",
                 "## Flagship Product Systems", "## Selected Product Ecosystem", "## Selected Collaborations",
                 "## Engineering Approach", "## Complete Project Archive", "## Contact"]
        positions = [self.readme.index(s) for s in order]
        self.assertEqual(positions, sorted(positions))

    def test_collaborations_are_included(self):
        block = self.readme[self.readme.index("## Selected Collaborations"):self.readme.index("## Engineering Approach")]
        for name in ("Sticker & Label Studio", "Couples Companion App", "Invitation Design Studio", "Product Photo Studio"):
            self.assertIn(name, block)
        self.assertIn("Built in collaboration", block)

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
        self.assertGreaterEqual(len(pictures), 5)
        for pic in pictures:
            self.assertIn('media="(prefers-color-scheme: dark)"', pic)
            self.assertIn('media="(prefers-color-scheme: light)"', pic)
            self.assertRegex(pic, r'<img alt="[^"]{10,}" src="assets/v5/[^"]+-light\.svg" width="100%">')
            dark = re.search(r'dark\)" srcset="([^"]+)"', pic).group(1)
            light = re.search(r'light\)" srcset="([^"]+)"', pic).group(1)
            self.assertEqual(dark.replace("-dark.svg", ""), light.replace("-light.svg", ""))

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
        archive = self.readme.index("## Complete Project Archive")
        for s in ("### Navlonix", "## Selected Product Ecosystem", "## Selected Collaborations"):
            self.assertLess(self.readme.index(s), archive)


class AssetTests(unittest.TestCase):
    def setUp(self):
        self.dir = os.path.join(ROOT, "assets", "v5")
        self.files = sorted(f for f in os.listdir(self.dir) if f.endswith(".svg"))

    def test_expected_asset_set(self):
        expected = {f"{n}-{t}.svg" for t in ("light", "dark")
                    for n in ["hero", "proof-strip"] + [f"flagship-{pid}" for pid in ra.FLAGSHIPS]}
        self.assertEqual(set(self.files), expected)

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

    def test_text_sizes_are_mobile_readable(self):
        # 1200 px logical width renders at ~350 px on a phone; keep every glyph >= 22 px (~6.5 px rendered) and
        # every primary label >= 28 px.
        for name in self.files:
            root = ET.fromstring(read(os.path.join(self.dir, name)))
            sizes = [float(t.get("font-size")) for t in root.iter(f"{SVG_NS}text")]
            self.assertTrue(sizes, name)
            self.assertGreaterEqual(min(sizes), 22, name)
            self.assertGreaterEqual(max(sizes), 46, name)

    def test_system_fonts_only(self):
        for name in self.files:
            svg = read(os.path.join(self.dir, name))
            for fam in set(re.findall(r'font-family="([^"]+)"', svg)):
                self.assertIn(fam, (ra.SANS, ra.MONO), name)

    def test_assets_are_reproducible_from_the_renderer(self):
        with open(os.path.join(ROOT, "data", "footprint.json"), encoding="utf-8") as fh:
            fp = json.load(fh)
        for rel, content in ra.render_all(fp).items():
            self.assertEqual(read(os.path.join(ROOT, rel)), content, rel)

    def test_proof_strip_is_data_driven(self):
        fp = {"measured_on": "2026-01-01", "window": {"label": "W"},
              "metrics": [{"key": "a", "value": 1234, "label": "Alpha things"}, {"key": "b", "value": 5, "label": "Beta"}]}
        svg = ra.render_proof_strip(fp, "light")
        self.assertIn("1,234", svg)
        self.assertIn("Alpha things", svg)
        ET.fromstring(svg)


if __name__ == "__main__":
    unittest.main()
