#!/usr/bin/env python3
"""Render the Editorial Master V5 SVG assets (assets/v5/).

Every asset is rendered twice from the same geometry — once per theme — so the
light and dark versions line up exactly. The SVGs are plain XML: system font
stacks only, no external resources, no scripts, no filters, no animation.

Assets:
  hero-{light,dark}.svg           editorial hero (name, title, mark)
  proof-strip-{light,dark}.svg    four verified metrics from data/footprint.json
  flagship-<id>-{light,dark}.svg  one system diagram per flagship product

Text sizes are chosen so that a 1200 px wide asset stays readable when GitHub
scales it into a ~350 px wide mobile README column (numbers >= 80 px, labels
>= 30 px in SVG units).  Standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Iterable

ASSET_DIR = os.path.join("assets", "v5")
SANS = "'Segoe UI', 'Helvetica Neue', Helvetica, Arial, sans-serif"
MONO = "Consolas, 'SFMono-Regular', Menlo, monospace"

THEMES = {
    "light": {
        "bg": "#F6F4EF", "fg": "#16181D", "muted": "#5C6270", "surface": "#ECEDF0",
        "surface2": "#E2E4E9", "rule": "#D3D6DC", "accent": "#2F4BC7", "accent_soft": "#DDE3F7",
        "accent2": "#8A94A8", "on_accent": "#FFFFFF",
    },
    "dark": {
        "bg": "#101216", "fg": "#F1EEE6", "muted": "#9AA1B0", "surface": "#1A1D24",
        "surface2": "#232730", "rule": "#2B2F38", "accent": "#7A90EE", "accent_soft": "#232A45",
        "accent2": "#6B7386", "on_accent": "#0F1220",
    },
}

WIDTH = 1200

# Flagship diagrams: verified system structure only (see data/portfolio.json).
FLAGSHIPS = {
    "navlonix": {
        "index": "01",
        "name": "Navlonix",
        "label": "Logistics marketplace",
        "surfaces_title": "Surfaces",
        "surfaces": ["Customer apps", "Driver app", "Admin panel"],
        "core_title": ".NET 9 API",
        "core": ["Fair pricing", "Escrow ledger", "Live tracking"],
        "foundation_title": "Foundations",
        "foundation": ["PostgreSQL · PostGIS", "Redis · SignalR", "Gemini AI"],
    },
    "nilufer-ilaclama": {
        "index": "02",
        "name": "Nilüfer İlaçlama",
        "label": "Field-service operations suite",
        "surfaces_title": "Surfaces",
        "surfaces": ["Admin panel", "Field mobile app", "Public site & portal"],
        "core_title": "Operations API",
        "core": ["Roles & permissions", "Jobs · contracts", "Payments · audit"],
        "foundation_title": "Foundations",
        "foundation": ["PostgreSQL · Prisma", "Supabase RLS portal", "Notifications"],
    },
    "salih-ai-company": {
        "index": "03",
        "name": "SALIH-AI-COMPANY",
        "label": "Multi-agent operating system",
        "surfaces_title": "Agents",
        "surfaces": ["Executive planner", "Engineering & research", "Quality · Security"],
        "core_title": "Policy engine",
        "core": ["Action levels L0–L5", "Bounded execution", "Human approval gate"],
        "foundation_title": "Foundations",
        "foundation": ["SQLite · audit chain", "Job queue · watchdogs", "Project registry"],
    },
}


# --------------------------------------------------------------------------- primitives

def xml(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def text_width(text: str, size: float, weight: str = "normal", mono: bool = False) -> float:
    """Rough width estimate for layout decisions (system sans / mono)."""
    per = 0.60 if mono else (0.50 if weight in ("600", "700", "bold") else 0.46)
    return len(text) * size * per


def text(x: float, y: float, s: str, size: float, fill: str, weight: str = "normal",
         anchor: str = "start", mono: bool = False, spacing: float | None = None) -> str:
    fam = MONO if mono else SANS
    attrs = [f'x="{x:.0f}"', f'y="{y:.0f}"', f'font-family="{fam}"', f'font-size="{size:g}"', f'fill="{fill}"']
    if weight != "normal":
        attrs.append(f'font-weight="{weight}"')
    if anchor != "start":
        attrs.append(f'text-anchor="{anchor}"')
    if spacing is not None:
        attrs.append(f'letter-spacing="{spacing:g}"')
    return f"<text {' '.join(attrs)}>{xml(s)}</text>"


def rect(x: float, y: float, w: float, h: float, fill: str, rx: float = 0, stroke: str = "", sw: float = 1) -> str:
    s = f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{fill}"'
    if rx:
        s += f' rx="{rx:g}"'
    if stroke:
        s += f' stroke="{stroke}" stroke-width="{sw:g}"'
    return s + "/>"


def line(x1: float, y1: float, x2: float, y2: float, stroke: str, sw: float = 1.5) -> str:
    return f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{stroke}" stroke-width="{sw:g}"/>'


def svg(width: int, height: int, title: str, desc: str, body: Iterable[str], bg: str) -> str:
    head = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="t d">',
        f'  <title id="t">{xml(title)}</title>',
        f'  <desc id="d">{xml(desc)}</desc>',
        f'  {rect(0, 0, width, height, bg)}',
    ]
    return "\n".join(head + [f"  {b}" for b in body] + ["</svg>"]) + "\n"


# --------------------------------------------------------------------------- hero

def render_hero(theme: str) -> str:
    t = THEMES[theme]
    w, h = WIDTH, 300
    m = 56
    body = [
        rect(0.5, 0.5, w - 1, h - 1, "none", rx=16, stroke=t["rule"]),
        text(m, 78, "HILMI SALIH ALTINIŞIK", 22, t["muted"], mono=True, spacing=3),
        text(m, 148, "Software Engineer", 62, t["fg"], weight="700", spacing=-1.5),
        text(m, 216, "& Product Builder", 62, t["fg"], weight="700", spacing=-1.5),
        rect(m, 249, 96, 4, t["accent"]),
        text(m + 116, 258, "architecture to launch", 22, t["muted"], mono=True, spacing=1),
        line(m + 440, 251, m + 640, 251, t["rule"], 2),
    ]
    # Editorial mark: three product surfaces over one foundation, one accent block.
    ox, oy = 840, 62
    body += [
        rect(ox, oy, 304, 40, t["surface"], rx=6),
        rect(ox, oy + 52, 304, 40, t["surface"], rx=6),
        rect(ox, oy + 104, 304, 40, t["surface"], rx=6),
        rect(ox, oy + 168, 304, 8, t["rule"], rx=4),
        rect(ox, oy + 168, 128, 8, t["accent"], rx=4),
        rect(ox + 16, oy + 12, 88, 16, t["surface2"], rx=3),
        rect(ox + 16, oy + 64, 136, 16, t["surface2"], rx=3),
        rect(ox + 16, oy + 116, 112, 16, t["surface2"], rx=3),
        rect(ox + 248, oy + 12, 40, 16, t["accent"], rx=3),
        rect(ox + 248, oy + 64, 40, 16, t["accent_soft"], rx=3),
        rect(ox + 248, oy + 116, 40, 16, t["accent_soft"], rx=3),
    ]
    return svg(w, h, "Hilmi Salih Altınışık — Software Engineer & Product Builder",
               "Editorial hero: name, title and an abstract mark of product surfaces over one foundation.",
               body, t["bg"])


# --------------------------------------------------------------------------- proof strip

def render_proof_strip(footprint: dict, theme: str) -> str:
    t = THEMES[theme]
    metrics = list(footprint["metrics"][:4])
    w, h = WIDTH, 236
    m = 48
    labels = [str(x.get("short_label") or x["label"]) for x in metrics]
    label_size = 32
    # Column widths follow label widths so nothing overlaps; numbers stay >= 80 px.
    raw = [max(text_width(lbl, label_size) + 56, 240) for lbl in labels]
    avail = w - 2 * m
    scale = avail / sum(raw)
    widths = [r * scale for r in raw]
    body = [rect(0.5, 0.5, w - 1, h - 1, "none", rx=16, stroke=t["rule"])]
    x = float(m)
    for i, (metric, lbl, cw) in enumerate(zip(metrics, labels, widths)):
        if i:
            body.append(line(x - 24, 60, x - 24, h - 60, t["rule"], 1.5))
        body.append(text(x, 122, format(int(metric["value"]), ","), 84, t["fg"], weight="700", spacing=-2))
        body.append(text(x, 172, lbl, label_size, t["muted"]))
        x += cw
    body.append(rect(m, h - 34, 96, 4, t["accent"]))
    window = footprint.get("window", {}).get("label", "")
    summary = "; ".join(f"{int(x['value']):,} {x['label'].lower()}" for x in metrics)
    return svg(w, h, f"Verified engineering footprint · {window}",
               f"{summary}. Measured with the GitHub API on {footprint.get('measured_on', '')}.",
               body, t["bg"])


# --------------------------------------------------------------------------- flagship diagrams

def fit_size(label: str, max_width: float, size: float, weight: str = "normal", floor: float = 24) -> float:
    """Largest font size <= size at which the label fits max_width (never below floor)."""
    while size > floor and text_width(label, size, weight) > max_width:
        size -= 1
    return size


def _box(x: float, y: float, w: float, h: float, label: str, t: dict, accent: bool = False, size: float = 28) -> list[str]:
    fill = t["accent_soft"] if accent else t["surface"]
    out = [rect(x, y, w, h, fill, rx=8)]
    if accent:
        out.append(rect(x, y, 6, h, t["accent"], rx=3))
    out.append(text(x + 22, y + h / 2 + size * 0.36, label, size, t["fg"], weight="600" if accent else "normal"))
    return out


def render_flagship(spec: dict, theme: str) -> str:
    t = THEMES[theme]
    w, h = WIDTH, 400
    m = 48
    body = [rect(0.5, 0.5, w - 1, h - 1, "none", rx=16, stroke=t["rule"])]
    # Title row
    body.append(text(m, 54, f"FLAGSHIP {spec['index']}", 22, t["accent"], mono=True, spacing=3))
    body.append(text(m, 100, spec["name"], 46, t["fg"], weight="700", spacing=-1))
    body.append(text(w - m, 100, spec["label"], 28, t["muted"], anchor="end"))
    body.append(line(m, 122, w - m, 122, t["rule"], 1.5))

    # Three columns: surfaces | core | foundations
    col_gap = 44
    col_w = (w - 2 * m - 2 * col_gap) / 3
    x1 = m
    x2 = m + col_w + col_gap
    x3 = m + 2 * (col_w + col_gap)
    top = 156
    body.append(text(x1, top, spec["surfaces_title"].upper(), 22, t["muted"], mono=True, spacing=2))
    body.append(text(x2, top, spec["core_title"].upper(), 22, t["accent"], mono=True, spacing=2))
    body.append(text(x3, top, spec["foundation_title"].upper(), 22, t["muted"], mono=True, spacing=2))

    box_h, gap = 60, 14
    y0 = top + 20
    # One uniform label size per diagram: the largest size at which every label fits.
    labels = spec["surfaces"][:3] + spec["foundation"][:3] + spec["core"][:3]
    size = min(fit_size(lbl, col_w - 44, 28, "600") for lbl in labels)
    for i, label in enumerate(spec["surfaces"][:3]):
        body += _box(x1, y0 + i * (box_h + gap), col_w, box_h, label, t, size=size)
    for i, label in enumerate(spec["foundation"][:3]):
        body += _box(x3, y0 + i * (box_h + gap), col_w, box_h, label, t, size=size)
    core_h = 3 * box_h + 2 * gap
    body.append(rect(x2, y0, col_w, core_h, t["accent_soft"], rx=10))
    body.append(rect(x2, y0, 6, core_h, t["accent"], rx=3))
    for i, label in enumerate(spec["core"][:3]):
        body.append(text(x2 + 26, y0 + 42 + i * 66, label, size, t["fg"], weight="600"))
    # Connectors between columns (arrows are implied by reading direction).
    mid = y0 + core_h / 2
    body.append(line(x1 + col_w, mid, x2, mid, t["accent2"], 2))
    body.append(line(x2 + col_w, mid, x3, mid, t["accent2"], 2))
    body.append(f'<circle cx="{x2:.1f}" cy="{mid:.1f}" r="5" fill="{t["accent"]}"/>')
    body.append(f'<circle cx="{x3:.1f}" cy="{mid:.1f}" r="5" fill="{t["accent"]}"/>')
    desc = (f"{spec['name']} system diagram. {spec['surfaces_title']}: {', '.join(spec['surfaces'])}. "
            f"{spec['core_title']}: {', '.join(spec['core'])}. {spec['foundation_title']}: {', '.join(spec['foundation'])}.")
    return svg(w, h, f"{spec['name']} — {spec['label']}", desc, body, t["bg"])


# --------------------------------------------------------------------------- entry points

def asset_path(name: str, theme: str, asset_dir: str = ASSET_DIR) -> str:
    return os.path.join(asset_dir, f"{name}-{theme}.svg")


def render_all(footprint: dict) -> dict[str, str]:
    """Return {relative path: svg text} for every V5 asset."""
    out: dict[str, str] = {}
    for theme in THEMES:
        out[asset_path("hero", theme)] = render_hero(theme)
        out[asset_path("proof-strip", theme)] = render_proof_strip(footprint, theme)
        for pid, spec in FLAGSHIPS.items():
            out[asset_path(f"flagship-{pid}", theme)] = render_flagship(spec, theme)
    return out


def write_if_changed(path: str, content: str) -> bool:
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
    parser = argparse.ArgumentParser(description="Render the V5 SVG assets")
    parser.add_argument("--footprint", default=os.path.join("data", "footprint.json"))
    args = parser.parse_args(argv)
    with open(args.footprint, encoding="utf-8") as fh:
        footprint = json.load(fh)
    changed = [p for p, content in render_all(footprint).items() if write_if_changed(p, content)]
    print(f"render-assets: {len(changed)} file(s) written" + (": " + ", ".join(changed) if changed else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
