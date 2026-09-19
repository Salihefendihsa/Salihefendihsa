#!/usr/bin/env python3
"""Generate the "Project Index" block in README.md from public repositories.

Selection rules (all must hold):
  public · owned by OWNER · not a fork · not archived · not disabled ·
  not the profile repository itself · has a non-empty description ·
  carries the `portfolio` topic.

Ordering: repositories with the `featured` topic first, then by last push
(newest first), then by name for a stable tie-break.

Only the text between the START/END markers in README.md is replaced.
Standard library only. The token (if any) is read from GITHUB_TOKEN and is
never printed. Private repositories are never requested (the public
/users/{owner}/repos endpoint is used) and never logged.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
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

REQUIRED_TOPIC = "portfolio"
FEATURED_TOPIC = "featured"
CATEGORY_LABELS = {
    "category-ai": "AI",
    "category-web": "Web",
    "category-mobile": "Mobile",
    "category-backend": "Backend",
    "category-tools": "Tools",
}
STATUS_LABELS = {
    "status-live": "Live",
    "status-building": "Building",
    "status-maintained": "Maintained",
    "status-experimental": "Experimental",
}

HEADER_LINES = [
    START_MARKER,
    "<!-- Generated automatically from public repositories tagged with `portfolio`. -->",
    "",
    "## Project Index",
    "",
    "<sub>Automatically updated from public repositories tagged with `portfolio`.</sub>",
    "",
    "",
]
EMPTY_NOTE = "_No projects are tagged yet. Add the `portfolio` topic to a public repository to list it here._"


class IndexError_(Exception):
    """Raised for any condition under which README.md must not be modified."""


# --------------------------------------------------------------------------- fetch

def fetch_public_repos(owner: str = OWNER, opener: Callable[[urllib.request.Request], Any] | None = None) -> list[dict]:
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
            with opener(req, timeout=TIMEOUT_SECONDS) as resp:  # type: ignore[call-arg]
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


# --------------------------------------------------------------------------- select / sort

def is_eligible(repo: dict, owner: str = OWNER, profile_repo: str = PROFILE_REPO) -> bool:
    if repo.get("private") or repo.get("visibility", "public") != "public":
        return False
    if (repo.get("owner") or {}).get("login", "").lower() != owner.lower():
        return False
    if repo.get("fork") or repo.get("archived") or repo.get("disabled"):
        return False
    if repo.get("name", "").lower() == profile_repo.lower():
        return False
    if not (repo.get("description") or "").strip():
        return False
    topics = {t.lower() for t in (repo.get("topics") or [])}
    return REQUIRED_TOPIC in topics


def _pushed_ts(repo: dict) -> float:
    value = repo.get("pushed_at") or ""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def select_and_sort(repos: Iterable[dict], owner: str = OWNER, profile_repo: str = PROFILE_REPO) -> list[dict]:
    chosen = [r for r in repos if is_eligible(r, owner, profile_repo)]
    chosen.sort(key=lambda r: (
        0 if FEATURED_TOPIC in {t.lower() for t in (r.get("topics") or [])} else 1,
        -_pushed_ts(r),
        r.get("name", "").lower(),
    ))
    return chosen


# --------------------------------------------------------------------------- render

_MD_SPECIAL = re.compile(r"([\\`*_\[\]|<>~])")


def escape_md(text: str) -> str:
    """Escape Markdown/HTML-significant characters and collapse whitespace."""
    text = " ".join((text or "").split())
    return _MD_SPECIAL.sub(r"\\\1", text)


def code_span(text: str) -> str:
    """Text for use inside a Markdown code span (backticks are not allowed there)."""
    return " ".join((text or "").replace("`", "").split())


def category_of(topics: Iterable[str]) -> str | None:
    for t in topics:
        if t.lower() in CATEGORY_LABELS:
            return CATEGORY_LABELS[t.lower()]
    return None


def status_of(topics: Iterable[str]) -> str | None:
    for t in topics:
        if t.lower() in STATUS_LABELS:
            return STATUS_LABELS[t.lower()]
    return None


def _is_http_url(url: str) -> bool:
    return bool(url) and url.lower().startswith(("https://", "http://"))


def render_entry(repo: dict) -> str:
    name = escape_md(repo.get("name", ""))
    url = repo.get("html_url", "")
    desc = escape_md(repo.get("description", ""))
    topics = repo.get("topics") or []
    chips = []
    if repo.get("language"):
        chips.append(f"`{code_span(repo['language'])}`")
    cat = category_of(topics)
    if cat:
        chips.append(f"`{cat}`")
    st = status_of(topics)
    if st:
        chips.append(f"`{st}`")
    links = [f"[Repository]({url})"]
    homepage = (repo.get("homepage") or "").strip()
    if _is_http_url(homepage):
        links.append(f"[Live Demo]({homepage})")
    lines = [f"### [{name}]({url})", "", desc, ""]
    if chips:
        lines.append(" · ".join(chips) + "<br>")
    lines.append(" · ".join(links))
    return "\n".join(lines)


def render_block(repos: list[dict]) -> str:
    body = [render_entry(r) for r in repos] if repos else [EMPTY_NOTE]
    return "\n".join(HEADER_LINES) + "\n\n".join(body) + "\n\n" + END_MARKER


# --------------------------------------------------------------------------- README update

def find_block(readme: str) -> tuple[int, int]:
    start = readme.find(START_MARKER)
    end = readme.find(END_MARKER)
    if start < 0 or end < 0 or end < start:
        raise IndexError_("README markers not found; refusing to modify the file")
    return start, end + len(END_MARKER)


def existing_block_has_entries(readme: str) -> bool:
    start, end = find_block(readme)
    return "\n### [" in readme[start:end]


def update_readme_text(readme: str, repos: list[dict]) -> str:
    start, end = find_block(readme)
    if not repos and existing_block_has_entries(readme):
        # Empty result must never wipe a previously generated index.
        return readme
    return readme[:start] + render_block(repos) + readme[end:]


# --------------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh the Project Index block in README.md")
    parser.add_argument("--readme", default="README.md")
    parser.add_argument("--output", default="generated/projects.md", help="also write the generated block here ('' to skip)")
    parser.add_argument("--input", help="read repositories from a JSON file instead of the GitHub API (testing)")
    parser.add_argument("--dry-run", action="store_true", help="print the block, do not write files")
    args = parser.parse_args(argv)

    try:
        with open(args.readme, encoding="utf-8") as fh:
            readme = fh.read()
        find_block(readme)  # validate markers before any network work

        if args.input:
            with open(args.input, encoding="utf-8") as fh:
                repos = json.load(fh)
        else:
            repos = fetch_public_repos()
        selected = select_and_sort(repos)
        new_readme = update_readme_text(readme, selected)
    except IndexError_ as exc:
        print(f"project-index: {exc} — README left unchanged", file=sys.stderr)
        return 1
    except (OSError, json.JSONDecodeError) as exc:
        print(f"project-index: {exc.__class__.__name__}: {exc} — README left unchanged", file=sys.stderr)
        return 1

    block = render_block(selected)
    if args.dry_run:
        print(block)
        return 0
    if new_readme != readme:
        with open(args.readme, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(new_readme)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        start, end = find_block(new_readme)
        with open(args.output, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(new_readme[start:end] + "\n")
    print(f"project-index: {len(selected)} project(s) listed; README {'updated' if new_readme != readme else 'unchanged'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
