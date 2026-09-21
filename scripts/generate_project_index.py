#!/usr/bin/env python3
"""Generate the project portfolio block in README.md and the footprint SVGs.

Two sources feed the block between the START/END markers:

  * Automatic  – public repositories owned by OWNER, fetched from the public
                 GitHub REST API (pagination followed). Forks, disabled repos
                 and the profile repository are skipped; `profile-hide` hides a
                 repository; `archived` state or the `archived` topic files it
                 under "Archived / Earlier Work"; `academic` / `experimental`
                 topics file it under "Academic & Experiments"; `category-*`
                 topics pick the portfolio table; `featured` (max 3 in total)
                 moves it to the top of its table.
  * Controlled – data/project_catalog.json, a public-safe catalog of private and
                 collaborative work. It carries display text only. The
                 generator refuses any github.com URL on a non-public entry so
                 a private repository can never be linked by accident.

The footprint SVGs (assets/editorial/engineering-footprint-*.svg) are rendered
from data/footprint.json so the numbers shown are exactly the measured ones.

Guarantees: deterministic output for the same input; only the marker region of
README.md is touched; Markdown table cells are escaped; invalid URLs are not
linked; an empty API result never wipes the existing block; the token (if any)
is read from GITHUB_TOKEN and never printed. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Iterable

OWNER = "Salihefendihsa"
PROFILE_REPO = OWNER  # profile README repository has the same name as the owner
API_BASE = "https://api.github.com"
PER_PAGE = 100
TIMEOUT_SECONDS = 20
MAX_PAGES = 20

START_MARKER = "<!-- PROJECT_INDEX:START -->"
END_MARKER = "<!-- PROJECT_INDEX:END -->"

DEFAULT_CATALOG = os.path.join("data", "project_catalog.json")
DEFAULT_FOOTPRINT = os.path.join("data", "footprint.json")
FOOTPRINT_SVG = {
    "dark": os.path.join("assets", "editorial", "engineering-footprint-dark.svg"),
    "light": os.path.join("assets", "editorial", "engineering-footprint-light.svg"),
}

MAX_FEATURED = 3
TABLE_COLUMNS = ("Project", "What it does", "Role · Access")  # three columns: fits a 380 px viewport without horizontal scroll

# Fixed category order. Tables render in this order; unknown categories are rejected.
CATEGORY_ORDER = (
    "Products & Platforms",
    "AI & Automation",
    "Web & Mobile",
    "Backend & APIs",
    "Desktop & Tools",
    "Collaborative Work",
    "Academic & Experiments",
    "Archived / Earlier Work",
)
PORTFOLIO_CATEGORIES = CATEGORY_ORDER[:5]
COLLAB_CATEGORY = "Collaborative Work"
ACADEMIC_CATEGORY = "Academic & Experiments"
ARCHIVED_CATEGORY = "Archived / Earlier Work"

CATEGORY_TOPICS = {
    "category-product": "Products & Platforms",
    "category-platform": "Products & Platforms",
    "category-ai": "AI & Automation",
    "category-automation": "AI & Automation",
    "category-web": "Web & Mobile",
    "category-mobile": "Web & Mobile",
    "category-backend": "Backend & APIs",
    "category-api": "Backend & APIs",
    "category-desktop": "Desktop & Tools",
    "category-tools": "Desktop & Tools",
}
STATUS_TOPICS = {
    "status-live": "Live",
    "status-building": "Building",
    "status-maintained": "Maintained",
    "status-experimental": "Experimental",
    "status-archived": "Archived",
}
ACADEMIC_TOPICS = {"academic", "coursework", "lab", "experimental"}
ARCHIVED_TOPICS = {"archived"}
HIDE_TOPIC = "profile-hide"
FEATURED_TOPIC = "featured"

# Language fallback when nothing else classifies a public repository.
LANGUAGE_CATEGORY = {
    "typescript": "Web & Mobile", "javascript": "Web & Mobile", "html": "Web & Mobile",
    "css": "Web & Mobile", "vue": "Web & Mobile", "svelte": "Web & Mobile",
    "dart": "Web & Mobile", "kotlin": "Web & Mobile", "swift": "Web & Mobile",
    "python": "Backend & APIs", "go": "Backend & APIs", "java": "Backend & APIs",
    "rust": "Backend & APIs", "php": "Backend & APIs", "ruby": "Backend & APIs",
    "c#": "Desktop & Tools", "c++": "Desktop & Tools", "c": "Desktop & Tools",
}

ALLOWED_ACCESS = ("Public", "Private", "Confidential", "Collaborative · Public", "Collaborative · Private")
CATALOG_FIELDS = {
    "display_name", "safe_summary", "stack", "role", "access", "status",
    "category", "optional_public_url", "featured", "sort_order",
}
OVERRIDE_FIELDS = {"display_name", "safe_summary", "stack", "role", "status", "category", "featured"}

PUBLIC_DEFAULT_ROLE = "Solo engineer"


class IndexError_(Exception):
    """Raised for any condition under which README.md must not be modified."""


# --------------------------------------------------------------------------- model

@dataclass
class Project:
    name: str
    summary: str
    stack: str
    role: str
    access: str
    status: str
    category: str
    url: str = ""          # GitHub link, public repositories only
    live_url: str = ""     # verified http(s) homepage, public repositories only
    featured: bool = False
    sort_order: int = 0
    pushed_ts: float = 0.0
    source: str = "public"  # "public" | "catalog"
    extra: dict = field(default_factory=dict)

    @property
    def is_public(self) -> bool:
        return self.access in ("Public", "Collaborative · Public")


# --------------------------------------------------------------------------- fetch

def fetch_public_repos(owner: str = OWNER, opener: Callable[..., Any] | None = None) -> list[dict]:
    """Fetch all public repositories owned by `owner`, following pagination."""
    opener = opener or urllib.request.urlopen
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repos: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        url = f"{API_BASE}/users/{owner}/repos?type=owner&per_page={PER_PAGE}&page={page}&sort=full_name"
        req = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": f"{owner}-project-index",
        })
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with opener(req, timeout=TIMEOUT_SECONDS) as resp:
                status = getattr(resp, "status", 200)
                if status != 200:
                    raise IndexError_(f"GitHub API returned HTTP {status} for page {page}")
                batch = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise IndexError_(f"GitHub API HTTP error {exc.code} on page {page}") from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise IndexError_(f"GitHub API request failed on page {page}: {exc.__class__.__name__}") from None
        if not isinstance(batch, list):
            raise IndexError_("Unexpected API payload (expected a list)")
        repos.extend(batch)
        if len(batch) < PER_PAGE:
            break
    return repos


# --------------------------------------------------------------------------- helpers

_MD_SPECIAL = re.compile(r"([\\`*_\[\]|<>~])")


def escape_md(text: str) -> str:
    """Escape Markdown/HTML-significant characters and collapse whitespace (table safe)."""
    text = " ".join(str(text or "").split())
    return _MD_SPECIAL.sub(r"\\\1", text)


def cell(text: str) -> str:
    """Escaped table cell text; never empty so the table stays well formed."""
    out = escape_md(text)
    return out or "—"


def safe_http_url(url: str) -> str:
    """Return the URL if it is a plain absolute http(s) URL, otherwise ''."""
    url = (url or "").strip()
    if not url or any(ch.isspace() for ch in url) or any(ch in url for ch in "()<>\"'`"):
        return ""
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return ""
    if parts.scheme not in ("http", "https") or not parts.netloc or "." not in parts.netloc:
        return ""
    return url


def is_github_url(url: str) -> bool:
    try:
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
    except ValueError:
        return False
    return host == "github.com" or host.endswith(".github.com")


def expected_repo_url(owner: str, name: str) -> str:
    return f"https://github.com/{owner}/{name}"


def _pushed_ts(repo: dict) -> float:
    value = repo.get("pushed_at") or ""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _topics(repo: dict) -> set[str]:
    return {str(t).lower() for t in (repo.get("topics") or [])}


# --------------------------------------------------------------------------- public repositories

def is_listed(repo: dict, owner: str = OWNER, profile_repo: str = PROFILE_REPO) -> bool:
    """Whether a repository from the API should appear at all."""
    if repo.get("private") or repo.get("visibility", "public") != "public":
        return False
    if (repo.get("owner") or {}).get("login", "").lower() != owner.lower():
        return False
    if repo.get("fork") or repo.get("disabled"):
        return False
    if repo.get("name", "").lower() == profile_repo.lower():
        return False
    if HIDE_TOPIC in _topics(repo):
        return False
    return True


def public_category(repo: dict, override: dict) -> str:
    topics = _topics(repo)
    if repo.get("archived") or topics & ARCHIVED_TOPICS:
        return ARCHIVED_CATEGORY
    if override.get("category"):
        return override["category"]
    if topics & ACADEMIC_TOPICS:
        return ACADEMIC_CATEGORY
    for topic in sorted(topics):
        if topic in CATEGORY_TOPICS:
            return CATEGORY_TOPICS[topic]
    lang = (repo.get("language") or "").lower()
    return LANGUAGE_CATEGORY.get(lang, "Desktop & Tools" if lang else ACADEMIC_CATEGORY)


def public_status(repo: dict, override: dict) -> str:
    if override.get("status"):
        return override["status"]
    for topic in sorted(_topics(repo)):
        if topic in STATUS_TOPICS:
            return STATUS_TOPICS[topic]
    return "Archived" if repo.get("archived") else ""


def public_summary(repo: dict, override: dict) -> str:
    if override.get("safe_summary"):
        return override["safe_summary"]
    desc = " ".join((repo.get("description") or "").split())
    if desc:
        return desc
    lang = repo.get("language") or ""
    return f"{lang} repository; description not published yet." if lang else "Description not published yet."


def project_from_repo(repo: dict, overrides: dict, owner: str = OWNER) -> Project:
    name = repo.get("name", "")
    override = overrides.get(name) or {}
    url = expected_repo_url(owner, name)
    if safe_http_url(repo.get("html_url", "")) != url:
        raise IndexError_(f"unexpected repository URL for {name!r}; refusing to link it")
    live = safe_http_url(repo.get("homepage") or "")
    if live and is_github_url(live):
        live = ""  # a GitHub URL is not a live product link
    topics = _topics(repo)
    return Project(
        name=override.get("display_name") or name,
        summary=public_summary(repo, override),
        stack=override.get("stack") or (repo.get("language") or ""),
        role=override.get("role") or PUBLIC_DEFAULT_ROLE,
        access="Public",
        status=public_status(repo, override),
        category=public_category(repo, override),
        url=url,
        live_url=live,
        featured=bool(override.get("featured", FEATURED_TOPIC in topics)),
        sort_order=0,
        pushed_ts=_pushed_ts(repo),
        source="public",
    )


# --------------------------------------------------------------------------- catalog

def load_catalog(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    validate_catalog(data)
    return data


def validate_catalog(data: Any) -> None:
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        raise IndexError_("catalog must be an object with an 'entries' list")
    for i, entry in enumerate(data["entries"]):
        if not isinstance(entry, dict):
            raise IndexError_(f"catalog entry {i} is not an object")
        unknown = set(entry) - CATALOG_FIELDS
        if unknown:
            raise IndexError_(f"catalog entry {i} has disallowed field(s): {sorted(unknown)}")
        for key in ("display_name", "safe_summary", "category", "access"):
            if not str(entry.get(key, "")).strip():
                raise IndexError_(f"catalog entry {i} is missing {key!r}")
        if entry["category"] not in CATEGORY_ORDER:
            raise IndexError_(f"catalog entry {i} has unknown category {entry['category']!r}")
        if entry["access"] not in ALLOWED_ACCESS:
            raise IndexError_(f"catalog entry {i} has unknown access {entry['access']!r}")
        url = str(entry.get("optional_public_url") or "").strip()
        if url:
            if not safe_http_url(url):
                raise IndexError_(f"catalog entry {i} has an invalid URL")
            if "private" in entry["access"].lower() or entry["access"] == "Confidential":
                if is_github_url(url):
                    raise IndexError_(f"catalog entry {i} links a GitHub URL on a non-public entry")
    overrides = data.get("public_overrides") or {}
    if not isinstance(overrides, dict):
        raise IndexError_("'public_overrides' must be an object")
    for name, override in overrides.items():
        if name.startswith("$"):
            continue
        if not isinstance(override, dict):
            raise IndexError_(f"override {name!r} is not an object")
        unknown = set(override) - OVERRIDE_FIELDS
        if unknown:
            raise IndexError_(f"override {name!r} has disallowed field(s): {sorted(unknown)}")
        if override.get("category") and override["category"] not in CATEGORY_ORDER:
            raise IndexError_(f"override {name!r} has unknown category")


def catalog_overrides(data: dict) -> dict:
    return {k: v for k, v in (data.get("public_overrides") or {}).items() if not k.startswith("$")}


def project_from_entry(entry: dict) -> Project:
    access = entry["access"]
    url = str(entry.get("optional_public_url") or "").strip()
    url = safe_http_url(url)
    github = url if (url and is_github_url(url) and "Public" in access) else ""
    live = url if (url and not is_github_url(url)) else ""
    return Project(
        name=entry["display_name"],
        summary=entry["safe_summary"],
        stack=entry.get("stack") or "",
        role=entry.get("role") or "",
        access=access,
        status=entry.get("status") or "",
        category=entry["category"],
        url=github,
        live_url=live,
        featured=bool(entry.get("featured", False)),
        sort_order=int(entry.get("sort_order", 0) or 0),
        source="catalog",
    )


# --------------------------------------------------------------------------- assemble

def build_projects(repos: Iterable[dict], catalog: dict, owner: str = OWNER, profile_repo: str = PROFILE_REPO) -> list[Project]:
    overrides = catalog_overrides(catalog)
    projects = [project_from_repo(r, overrides, owner) for r in repos if is_listed(r, owner, profile_repo)]
    projects += [project_from_entry(e) for e in catalog.get("entries", [])]

    seen: dict[str, str] = {}
    for p in projects:
        key = " ".join(p.name.lower().split())
        if key in seen:
            raise IndexError_(f"duplicate project name {p.name!r}")
        seen[key] = p.name
        if p.category not in CATEGORY_ORDER:
            raise IndexError_(f"unknown category {p.category!r} for {p.name!r}")

    projects.sort(key=sort_key)
    featured = [p for p in projects if p.featured]
    for p in featured[MAX_FEATURED:]:
        p.featured = False
    projects.sort(key=sort_key)
    return projects


def sort_key(p: Project) -> tuple:
    return (0 if p.featured else 1, p.sort_order, -p.pushed_ts, p.name.lower())


# --------------------------------------------------------------------------- render

def render_project_cell(p: Project) -> str:
    name = cell(p.name)
    title = f"[{name}]({p.url})" if p.url else f"**{name}**"
    bits = []
    if p.featured:
        bits.append("Featured")
    if p.status:
        bits.append(escape_md(p.status))
    if p.live_url:
        bits.append(f"[Live]({p.live_url})")
    out = title
    if bits:
        out += f"<br><sub>{' · '.join(bits)}</sub>"
    if p.stack:
        out += f"<br><sub>Stack: {escape_md(p.stack)}</sub>"
    return out


def render_role_access_cell(p: Project) -> str:
    """Role and access on two small-type lines so the column stays narrow on phones."""
    parts = [f"<sub>{escape_md(x)}</sub>" for x in (p.role, p.access) if x]
    return "<br>".join(parts) or "—"


def render_row(p: Project) -> str:
    return "| " + " | ".join((render_project_cell(p), cell(p.summary), render_role_access_cell(p))) + " |"


def render_table(projects: list[Project]) -> list[str]:
    lines = ["| " + " | ".join(TABLE_COLUMNS) + " |", "| " + " | ".join("---" for _ in TABLE_COLUMNS) + " |"]
    lines += [render_row(p) for p in projects]
    return lines


def _group(projects: list[Project], predicate: Callable[[Project], bool]) -> dict[str, list[Project]]:
    grouped: dict[str, list[Project]] = {}
    for p in projects:
        if predicate(p):
            grouped.setdefault(p.category, []).append(p)
    return grouped


def render_block(projects: list[Project]) -> str:
    out: list[str] = [
        START_MARKER,
        "<!-- Generated by scripts/generate_project_index.py: public repositories from the GitHub API + data/project_catalog.json. Do not edit by hand. -->",
        "",
    ]

    public_portfolio = _group(projects, lambda p: p.source == "public" and p.category in PORTFOLIO_CATEGORIES)
    out += ["## Complete Project Portfolio", "",
            "<sub>Public repositories are discovered automatically from GitHub; private and collaborative work is described from a public-safe catalog.</sub>", ""]
    if public_portfolio:
        for category in PORTFOLIO_CATEGORIES:
            if category in public_portfolio:
                out += [f"### {category}", ""] + render_table(public_portfolio[category]) + [""]
    else:
        out += ["_No public projects to list yet._", ""]

    private = [p for p in projects if p.source == "catalog" and not p.is_public
               and p.category not in (COLLAB_CATEGORY, ACADEMIC_CATEGORY, ARCHIVED_CATEGORY)]
    out += ["## Private Products & Systems", "",
            "<sub>Products built for real businesses or under NDA. Names and details are limited to what can be shared publicly; no private repositories are linked.</sub>", ""]
    if private:
        out += render_table(private) + [""]
    else:
        out += ["_Nothing to show yet._", ""]

    collab = [p for p in projects if p.category == COLLAB_CATEGORY]
    out += ["## Collaborative Work", "",
            "<sub>Only repositories where my commits or pull requests are verifiable are listed. Ownership stays with the partner.</sub>", ""]
    if collab:
        out += render_table(collab) + [""]
    else:
        out += ["_Nothing to show yet._", ""]

    academic = [p for p in projects if p.category == ACADEMIC_CATEGORY]
    out += ["## Academic & Experiments", ""]
    if academic:
        out += ["<details>", f"<summary>University coursework, labs and small experiments ({len(academic)})</summary>", ""]
        out += render_table(academic) + ["", "</details>", ""]
    else:
        out += ["_Nothing to show yet._", ""]

    archived = [p for p in projects if p.category == ARCHIVED_CATEGORY]
    if archived:
        out += ["<details>", f"<summary>Archived / earlier work ({len(archived)})</summary>", ""]
        out += render_table(archived) + ["", "</details>", ""]

    out.append(END_MARKER)
    return "\n".join(out)


# --------------------------------------------------------------------------- footprint SVG

FOOTPRINT_THEMES = {
    "dark": {"bg": "#0B0D10", "border": "#262A33", "fg": "#F4F2EC", "muted": "#8B93A7", "accent": "#6C7CFF", "bar": "#1A1E27"},
    "light": {"bg": "#FFFFFF", "border": "#D9DCE3", "fg": "#14161B", "muted": "#5B6272", "accent": "#4A5BE0", "bar": "#ECEEF3"},
}
LANG_COLORS = ["#6C7CFF", "#9AA6FF", "#C1C8FF", "#7A85A8", "#A3ABC2", "#C7CCDA", "#DDE0E8"]


def _xml(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def render_footprint_svg(data: dict, theme: str) -> str:
    t = FOOTPRINT_THEMES[theme]
    metrics = data["metrics"][:4]
    langs = data.get("languages") or []
    window = data.get("window", {}).get("label", "")
    measured = data.get("measured_on", "")
    w, h = 1200, 350
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" '
        f'aria-label="Engineering footprint, {_xml(window)}: ' + "; ".join(f"{m['value']} {m['label']}" for m in metrics) + '">',
        f"  <title>Engineering footprint · {_xml(window)}</title>",
        "  <style>.fp-sans{font-family:'Segoe UI',Inter,Helvetica,Arial,sans-serif}.fp-mono{font-family:Consolas,'JetBrains Mono',Menlo,monospace}</style>",
        '  <defs><clipPath id="fp-bar"><rect x="64" y="244" width="1072" height="14" rx="7"/></clipPath></defs>',
        f'  <rect width="{w}" height="{h}" rx="14" fill="{t["bg"]}"/>',
        f'  <rect x="0.5" y="0.5" width="{w-1}" height="{h-1}" rx="14" fill="none" stroke="{t["border"]}"/>',
        f'  <text x="64" y="58" class="fp-mono" font-size="15" letter-spacing="2" fill="{t["muted"]}">ENGINEERING FOOTPRINT · {_xml(window.upper())}</text>',
    ]
    col_w = (w - 128) / max(len(metrics), 1)
    for i, m in enumerate(metrics):
        x = 64 + i * col_w
        lines += [
            f'  <text x="{x:.0f}" y="132" class="fp-sans" font-size="56" font-weight="700" fill="{t["fg"]}" letter-spacing="-1">{_xml(format(int(m["value"]), ","))}</text>',
            f'  <text x="{x:.0f}" y="164" class="fp-sans" font-size="18" font-weight="600" fill="{t["fg"]}">{_xml(m["label"])}</text>',
            f'  <text x="{x:.0f}" y="188" class="fp-sans" font-size="14" fill="{t["muted"]}">{_xml(m.get("note", ""))}</text>',
        ]
    lines.append(f'  <line x1="64" y1="216" x2="{w-64}" y2="216" stroke="{t["border"]}" stroke-width="1.5"/>')
    lines.append(f'  <rect x="64" y="215" width="72" height="3" fill="{t["accent"]}"/>')
    # language bar (clipped to rounded shape)
    bar_x, bar_y, bar_w, bar_h = 64, 244, w - 128, 14
    lines.append(f'  <rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="{bar_h}" rx="7" fill="{t["bar"]}"/>')
    total = sum(float(l.get("share", 0)) for l in langs) or 1.0
    x = float(bar_x)
    lines.append('  <g clip-path="url(#fp-bar)">')
    for i, l in enumerate(langs):
        seg = bar_w * float(l.get("share", 0)) / total
        lines.append(f'    <rect x="{x:.1f}" y="{bar_y}" width="{seg:.1f}" height="{bar_h}" fill="{LANG_COLORS[i % len(LANG_COLORS)]}"/>')
        x += seg
    lines.append("  </g>")
    lx = bar_x
    for i, l in enumerate(langs):
        label = f"{l['name']} {float(l.get('share', 0)):g}%"
        lines.append(f'  <rect x="{lx}" y="282" width="10" height="10" rx="2" fill="{LANG_COLORS[i % len(LANG_COLORS)]}"/>')
        lines.append(f'  <text x="{lx+16}" y="291" class="fp-sans" font-size="14" fill="{t["fg"]}">{_xml(label)}</text>')
        lx += 16 + int(len(label) * 8.4) + 30
    lines.append(f'  <text x="64" y="322" class="fp-mono" font-size="13" fill="{t["muted"]}">{_xml(data.get("languages_note", ""))} · measured {_xml(measured)}</text>')
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def load_footprint(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data.get("metrics"), list) or not data["metrics"]:
        raise IndexError_("footprint.json must contain a non-empty 'metrics' list")
    for m in data["metrics"]:
        if not isinstance(m.get("value"), int) or m["value"] < 0 or not m.get("label"):
            raise IndexError_("every footprint metric needs an integer 'value' and a 'label'")
    return data


# --------------------------------------------------------------------------- README update

def find_block(readme: str) -> tuple[int, int]:
    start = readme.find(START_MARKER)
    end = readme.find(END_MARKER)
    if start < 0 or end < 0 or end < start:
        raise IndexError_("README markers not found; refusing to modify the file")
    return start, end + len(END_MARKER)


def existing_block_has_entries(readme: str) -> bool:
    start, end = find_block(readme)
    return "\n| [" in readme[start:end] or "\n| **" in readme[start:end]


def update_readme_text(readme: str, projects: list[Project]) -> str:
    start, end = find_block(readme)
    if not projects and existing_block_has_entries(readme):
        # An empty result must never wipe a previously generated index.
        return readme
    return readme[:start] + render_block(projects) + readme[end:]


# --------------------------------------------------------------------------- main

def _write_if_changed(path: str, content: str) -> bool:
    try:
        with open(path, encoding="utf-8") as fh:
            if fh.read() == content:
                return False
    except OSError:
        pass
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh the project portfolio block in README.md")
    parser.add_argument("--readme", default="README.md")
    parser.add_argument("--catalog", default=DEFAULT_CATALOG)
    parser.add_argument("--footprint", default=DEFAULT_FOOTPRINT, help="footprint data ('' to skip SVG generation)")
    parser.add_argument("--output", default=os.path.join("generated", "projects.md"), help="also write the generated block here ('' to skip)")
    parser.add_argument("--input", help="read repositories from a JSON file instead of the GitHub API (testing)")
    parser.add_argument("--dry-run", action="store_true", help="print the block, do not write files")
    args = parser.parse_args(argv)

    try:
        with open(args.readme, encoding="utf-8") as fh:
            readme = fh.read()
        find_block(readme)  # validate markers before any network work
        catalog = load_catalog(args.catalog)
        footprint = load_footprint(args.footprint) if args.footprint else None

        if args.input:
            with open(args.input, encoding="utf-8") as fh:
                repos = json.load(fh)
        else:
            repos = fetch_public_repos()
        if not any(is_listed(r) for r in repos):
            raise IndexError_("the API returned no listable public repositories")
        projects = build_projects(repos, catalog)
        new_readme = update_readme_text(readme, projects)
    except IndexError_ as exc:
        print(f"project-index: {exc} — README left unchanged", file=sys.stderr)
        return 1
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(f"project-index: {exc.__class__.__name__}: {exc} — README left unchanged", file=sys.stderr)
        return 1

    block = render_block(projects)
    if args.dry_run:
        print(block)
        return 0
    changed = []
    if _write_if_changed(args.readme, new_readme):
        changed.append(args.readme)
    if args.output:
        start, end = find_block(new_readme)
        if _write_if_changed(args.output, new_readme[start:end] + "\n"):
            changed.append(args.output)
    if footprint:
        for theme, path in FOOTPRINT_SVG.items():
            if _write_if_changed(path, render_footprint_svg(footprint, theme)):
                changed.append(path)
    print(f"project-index: {len(projects)} project(s) listed; changed: {', '.join(changed) if changed else 'nothing'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
