#!/usr/bin/env python3
"""Render the Editorial Master V5 SVG assets (assets/v5/).

Every asset is rendered from one geometry per breakpoint and twice per theme,
so light and dark versions line up exactly. Desktop assets are 1200 px wide;
mobile assets are 720 px wide and recomposed (not scaled) with larger type so
they stay readable inside GitHub's ~350 px mobile README column. The SVGs are
plain XML: system font stacks only, no external resources, no scripts, no
filters, no animation.

Assets (each in -light / -dark):
  hero-desktop, hero-mobile               name, title, monogram, product-domain map
  proof-desktop, proof-mobile             four verified evidence cards + measurement timeline
  flagship-<id>                           one system diagram per flagship product
  ecosystem-desktop, ecosystem-mobile     product board (tier-2 products, from data/portfolio.json)
  collaborations-desktop, -mobile         verified collaboration board
  approach-desktop, approach-mobile       five-stage engineering process

Standard library only.
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

DESKTOP_W = 1200
MOBILE_W = 720

THEMES = {
    "light": {
        "bg": "#F6F4EF", "fg": "#16181D", "muted": "#5C6270", "surface": "#FFFFFF", "surface2": "#ECEDF0",
        "rule": "#D8DAE0", "accent": "#2F4BC7", "accent_soft": "#E4E8F8", "accent2": "#8A94A8",
        "dom_logistics": "#2F4BC7", "dom_field": "#1F7A6D", "dom_business": "#A3651F", "dom_ai": "#6B4FB8", "dom_studio": "#2F4BC7",
        "dom_logistics_soft": "#E4E8F8", "dom_field_soft": "#DFF0EC", "dom_business_soft": "#F6EBDC", "dom_ai_soft": "#ECE6F8", "dom_studio_soft": "#E4E8F8",
    },
    "dark": {
        "bg": "#101216", "fg": "#F1EEE6", "muted": "#9AA1B0", "surface": "#181B21", "surface2": "#22262E",
        "rule": "#2C3039", "accent": "#7A90EE", "accent_soft": "#232A45", "accent2": "#6B7386",
        "dom_logistics": "#7A90EE", "dom_field": "#5CC2B2", "dom_business": "#E0A45A", "dom_ai": "#A98BE8", "dom_studio": "#7A90EE",
        "dom_logistics_soft": "#1E2540", "dom_field_soft": "#17302C", "dom_business_soft": "#33281A", "dom_ai_soft": "#26203A", "dom_studio_soft": "#1E2540",
    },
}

DOMAINS = {
    "logistics": "Logistics",
    "field": "Field Operations",
    "business": "Business Systems",
    "ai": "Autonomous AI",
    "studio": "Studio",
}

# Hero product-domain map: verified products per domain (names only).
HERO_DOMAINS = [
    ("logistics", "Logistics", "Navlonix"),
    ("field", "Field Operations", "Nilüfer İlaçlama"),
    ("business", "Business Systems", "Finans Pro · Tatlı Durağı"),
    ("ai", "Autonomous AI", "SALIH-AI-COMPANY"),
]

APPROACH = [
    ("architecture", "Architecture", "Define the system before scaling it."),
    ("boundaries", "Typed Boundaries", "Make responsibilities and contracts explicit."),
    ("testable", "Testable Workflows", "Prove behaviour before widening scope."),
    ("approval", "Human Approval", "Keep consequential AI actions supervised."),
    ("observe", "Observe & Improve", "Measure real operation and iterate."),
]

# Flagship diagrams: verified system structure only (see data/portfolio.json).
FLAGSHIPS = {
    "navlonix": {
        "index": "01", "name": "Navlonix", "label": "Logistics marketplace", "domain": "logistics",
        "surfaces_title": "Surfaces", "surfaces": ["Customer apps", "Driver app", "Admin panel"],
        "core_title": ".NET 9 API", "core": ["Fair pricing", "Escrow ledger", "Live tracking"],
        "foundation_title": "Foundations", "foundation": ["PostgreSQL · PostGIS", "Redis · SignalR", "Gemini AI"],
    },
    "nilufer-ilaclama": {
        "index": "02", "name": "Nilüfer İlaçlama", "label": "Field-service operations suite", "domain": "field",
        "surfaces_title": "Surfaces", "surfaces": ["Admin panel", "Field mobile app", "Public site & portal"],
        "core_title": "Operations API", "core": ["Roles & permissions", "Jobs · contracts", "Payments · audit"],
        "foundation_title": "Foundations", "foundation": ["PostgreSQL · Prisma", "Supabase RLS portal", "Notifications"],
    },
    "salih-ai-company": {
        "index": "03", "name": "SALIH-AI-COMPANY", "label": "Multi-agent operating system", "domain": "ai",
        "surfaces_title": "Agents", "surfaces": ["Executive planner", "Engineering & research", "Quality · Security"],
        "core_title": "Policy engine", "core": ["Action levels L0–L5", "Bounded execution", "Human approval gate"],
        "foundation_title": "Foundations", "foundation": ["SQLite · audit chain", "Job queue · watchdogs", "Project registry"],
    },
}


# --------------------------------------------------------------------------- primitives

def xml(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def text_width(text: str, size: float, weight: str = "normal", mono: bool = False) -> float:
    """Rough width estimate for layout decisions (system sans / mono)."""
    per = 0.62 if mono else (0.56 if weight in ("600", "700", "bold") else 0.51)
    return len(text) * size * per


def fit_size(label: str, max_width: float, size: float, weight: str = "normal", floor: float = 18, mono: bool = False) -> float:
    """Largest font size <= size at which the label fits max_width (never below floor)."""
    while size > floor and text_width(label, size, weight, mono) > max_width:
        size -= 1
    return size


def wrap(text: str, size: float, max_width: float, weight: str = "normal", max_lines: int = 3) -> list[str]:
    """Greedy word wrap using the width estimate; the last line is truncated with an ellipsis if needed."""
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if cur and text_width(trial, size, weight) > max_width:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while lines[-1] and text_width(lines[-1] + "…", size, weight) > max_width:
            lines[-1] = lines[-1].rsplit(" ", 1)[0] if " " in lines[-1] else lines[-1][:-1]
        lines[-1] += "…"
    return lines


def text(x: float, y: float, s: str, size: float, fill: str, weight: str = "normal",
         anchor: str = "start", mono: bool = False, spacing: float | None = None, italic: bool = False) -> str:
    fam = MONO if mono else SANS
    attrs = [f'x="{x:.0f}"', f'y="{y:.0f}"', f'font-family="{fam}"', f'font-size="{size:g}"', f'fill="{fill}"']
    if weight != "normal":
        attrs.append(f'font-weight="{weight}"')
    if italic:
        attrs.append('font-style="italic"')
    if anchor != "start":
        attrs.append(f'text-anchor="{anchor}"')
    if spacing is not None:
        attrs.append(f'letter-spacing="{spacing:g}"')
    return f"<text {' '.join(attrs)}>{xml(s)}</text>"


def lines_block(x: float, y: float, lines: list[str], size: float, fill: str, leading: float, **kw) -> list[str]:
    return [text(x, y + i * leading, ln, size, fill, **kw) for i, ln in enumerate(lines)]


def rect(x: float, y: float, w: float, h: float, fill: str, rx: float = 0, stroke: str = "", sw: float = 1) -> str:
    s = f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{fill}"'
    if rx:
        s += f' rx="{rx:g}"'
    if stroke:
        s += f' stroke="{stroke}" stroke-width="{sw:g}"'
    return s + "/>"


def line(x1: float, y1: float, x2: float, y2: float, stroke: str, sw: float = 1.5, dash: str = "") -> str:
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{stroke}" stroke-width="{sw:g}"{d}/>'


def circle(cx: float, cy: float, r: float, fill: str, stroke: str = "", sw: float = 1.5) -> str:
    s = f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:g}" fill="{fill}"'
    if stroke:
        s += f' stroke="{stroke}" stroke-width="{sw:g}"'
    return s + "/>"


def path(d: str, stroke: str, sw: float = 2, fill: str = "none") -> str:
    return f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{sw:g}" stroke-linecap="round" stroke-linejoin="round"/>'


def card(x: float, y: float, w: float, h: float, t: dict, accent: str = "", rx: float = 14) -> list[str]:
    out = [rect(x, y, w, h, t["surface"], rx=rx, stroke=t["rule"])]
    if accent:
        out.append(rect(x, y + 22, 5, h - 44, accent, rx=2.5))
    return out


def svg(width: int, height: int, title: str, desc: str, body: Iterable[str], bg: str) -> str:
    head = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="t d">',
        f'  <title id="t">{xml(title)}</title>',
        f'  <desc id="d">{xml(desc)}</desc>',
        f'  {rect(0, 0, width, height, bg)}',
    ]
    return "\n".join(head + [f"  {b}" for b in body] + ["</svg>"]) + "\n"


# --------------------------------------------------------------------------- glyph family
# Every glyph is drawn inside a box of side `s` at (x, y) on a 24-unit grid with rounded strokes.

def glyph(name: str, x: float, y: float, s: float, color: str, soft: str = "") -> list[str]:
    u = s / 24.0
    X = lambda v: x + v * u  # noqa: E731
    Y = lambda v: y + v * u  # noqa: E731
    sw = max(1.6, 2 * u)
    g: list[str] = []
    if name == "monogram":  # H and S built from strokes; the A is implied by the accent apex on the plate
        g += [path(f"M{X(3)} {Y(4)} V{Y(20)} M{X(9)} {Y(4)} V{Y(20)} M{X(3)} {Y(12)} H{X(9)}", color, sw),
              path(f"M{X(20)} {Y(6)} H{X(14)} V{Y(12)} H{X(20)} V{Y(18)} H{X(14)}", color, sw)]
    elif name == "logistics":  # route: two stops joined by a road
        g += [circle(X(5), Y(18), 3 * u, "none", color, sw), circle(X(19), Y(6), 3 * u, "none", color, sw),
              path(f"M{X(7.5)} {Y(16)} C{X(14)} {Y(16)} {X(10)} {Y(8)} {X(16.5)} {Y(8)}", color, sw)]
    elif name == "field":  # field marker over ground
        g += [path(f"M{X(12)} {Y(20)} L{X(6)} {Y(11)} A{6*u:.1f} {6*u:.1f} 0 1 1 {X(18)} {Y(11)} Z", color, sw),
              circle(X(12), Y(10), 2.2 * u, color), line(X(3), Y(22), X(21), Y(22), color, sw)]
    elif name == "business":  # ledger lines with a totals rule
        g += [path(f"M{X(4)} {Y(6)} H{X(20)} M{X(4)} {Y(11)} H{X(16)} M{X(4)} {Y(16)} H{X(18)}", color, sw),
              line(X(4), Y(21), X(20), Y(21), color, sw * 1.6)]
    elif name == "ai":  # node graph
        g += [circle(X(12), Y(12), 3.2 * u, color), circle(X(4), Y(5), 2.2 * u, "none", color, sw),
              circle(X(20), Y(6), 2.2 * u, "none", color, sw), circle(X(18), Y(20), 2.2 * u, "none", color, sw),
              path(f"M{X(9.5)} {Y(9.8)} L{X(5.8)} {Y(6.6)} M{X(14.8)} {Y(10.2)} L{X(18.2)} {Y(7.4)} M{X(13.8)} {Y(14.6)} L{X(16.6)} {Y(18.2)}", color, sw)]
    elif name in ("studio", "system-map"):  # system map: grid of modules with one committed hub
        g += [rect(X(3), Y(3), 7 * u, 7 * u, "none", rx=1.5 * u, stroke=color, sw=sw), rect(X(14), Y(3), 7 * u, 7 * u, "none", rx=1.5 * u, stroke=color, sw=sw),
              rect(X(3), Y(14), 7 * u, 7 * u, "none", rx=1.5 * u, stroke=color, sw=sw), rect(X(14), Y(14), 7 * u, 7 * u, color, rx=1.5 * u),
              path(f"M{X(10)} {Y(6.5)} H{X(14)} M{X(6.5)} {Y(10)} V{Y(14)} M{X(17.5)} {Y(10)} V{Y(14)}", color, sw)]
    elif name == "inbox-approval":  # inbox tray with an approval tick badge
        g += [path(f"M{X(3)} {Y(13)} V{Y(19)} H{X(21)} V{Y(13)} M{X(3)} {Y(13)} L{X(6)} {Y(6)} H{X(18)} L{X(21)} {Y(13)} H{X(15)} L{X(13)} {Y(16)} H{X(11)} L{X(9)} {Y(13)} Z", color, sw),
              circle(X(19), Y(6), 4.2 * u, soft or "none", color, sw), path(f"M{X(17)} {Y(6)} L{X(18.5)} {Y(7.5)} L{X(21.2)} {Y(4.6)}", color, sw)]
    elif name == "ledger":  # portfolio columns with a trend line
        g += [rect(X(3), Y(13), 4 * u, 8 * u, "none", rx=u, stroke=color, sw=sw), rect(X(10), Y(9), 4 * u, 12 * u, "none", rx=u, stroke=color, sw=sw),
              rect(X(17), Y(5), 4 * u, 16 * u, color, rx=u), path(f"M{X(3)} {Y(8)} L{X(9)} {Y(5)} L{X(14)} {Y(6)}", color, sw)]
    elif name == "table-order":  # table grid with a QR corner and an order dot
        g += [rect(X(3), Y(3), 8 * u, 8 * u, "none", rx=u, stroke=color, sw=sw), rect(X(5.5), Y(5.5), 3 * u, 3 * u, color),
              rect(X(13), Y(3), 8 * u, 8 * u, "none", rx=u, stroke=color, sw=sw), rect(X(3), Y(13), 8 * u, 8 * u, "none", rx=u, stroke=color, sw=sw),
              circle(X(17), Y(17), 3.5 * u, color)]
    elif name == "vision":  # lens with crosshair
        g += [circle(X(12), Y(12), 8 * u, "none", color, sw), circle(X(12), Y(12), 3 * u, color),
              path(f"M{X(12)} {Y(1.5)} V{Y(5)} M{X(12)} {Y(19)} V{Y(22.5)} M{X(1.5)} {Y(12)} H{X(5)} M{X(19)} {Y(12)} H{X(22.5)}", color, sw)]
    elif name == "inventory":  # stacked crates on a counted row
        g += [rect(X(3), Y(12), 8 * u, 8 * u, "none", rx=u, stroke=color, sw=sw), rect(X(13), Y(12), 8 * u, 8 * u, "none", rx=u, stroke=color, sw=sw),
              rect(X(8), Y(3), 8 * u, 8 * u, color, rx=u), path(f"M{X(3)} {Y(23)} H{X(21)}", color, sw)]
    elif name == "collaboration":  # two contributors whose workstreams intersect
        g += [circle(X(8.5), Y(12), 6 * u, soft or "none", color, sw), circle(X(15.5), Y(12), 6 * u, "none", color, sw),
              circle(X(12), Y(12), 1.8 * u, color)]
    elif name == "commits":  # commit dot on a branch line
        g += [line(X(2), Y(12), X(22), Y(12), color, sw), circle(X(12), Y(12), 4 * u, soft or "none", color, sw), circle(X(12), Y(12), 1.6 * u, color)]
    elif name == "repositories":  # stacked layers
        g += [path(f"M{X(12)} {Y(4)} L{X(21)} {Y(9)} L{X(12)} {Y(14)} L{X(3)} {Y(9)} Z", color, sw),
              path(f"M{X(3)} {Y(14)} L{X(12)} {Y(19)} L{X(21)} {Y(14)}", color, sw)]
    elif name == "owned":  # box with a tab
        g += [path(f"M{X(3)} {Y(9)} V{Y(20)} H{X(21)} V{Y(9)} M{X(3)} {Y(9)} V{Y(5)} H{X(10)} L{X(12)} {Y(8)} H{X(21)} V{Y(9)}", color, sw),
              rect(X(3), Y(9), 18 * u, 2.2 * u, color)]
    elif name == "architecture":  # blueprint grid with one committed module
        g += [rect(X(3), Y(3), 18 * u, 18 * u, "none", rx=1.5 * u, stroke=color, sw=sw),
              path(f"M{X(9)} {Y(3)} V{Y(21)} M{X(15)} {Y(3)} V{Y(21)} M{X(3)} {Y(9)} H{X(21)} M{X(3)} {Y(15)} H{X(21)}", color, sw * 0.7),
              rect(X(9), Y(9), 6 * u, 6 * u, color)]
    elif name == "boundaries":  # explicit contract: bracketed block
        g += [path(f"M{X(8)} {Y(4)} H{X(4)} V{Y(20)} H{X(8)} M{X(16)} {Y(4)} H{X(20)} V{Y(20)} H{X(16)}", color, sw),
              rect(X(9), Y(9), 6 * u, 6 * u, color, rx=u)]
    elif name == "testable":  # check inside a circle
        g += [circle(X(12), Y(12), 9 * u, "none", color, sw), path(f"M{X(7.5)} {Y(12.5)} L{X(10.8)} {Y(15.8)} L{X(16.8)} {Y(8.8)}", color, sw * 1.2)]
    elif name == "approval":  # gate: two posts, a bar and the person who decides
        g += [path(f"M{X(4)} {Y(21)} V{Y(9)} M{X(20)} {Y(21)} V{Y(9)} M{X(4)} {Y(9)} H{X(20)}", color, sw),
              circle(X(12), Y(9), 3.2 * u, color), path(f"M{X(12)} {Y(12)} V{Y(18)}", color, sw)]
    elif name == "observe":  # gauge arc with a needle
        g += [path(f"M{X(3)} {Y(17)} A{9*u:.1f} {9*u:.1f} 0 0 1 {X(21)} {Y(17)}", color, sw),
              path(f"M{X(12)} {Y(17)} L{X(16)} {Y(10)}", color, sw), circle(X(12), Y(17), 2 * u, color),
              path(f"M{X(5)} {Y(12)} L{X(6.5)} {Y(13)} M{X(19)} {Y(12)} L{X(17.5)} {Y(13)}", color, sw)]
    return g


def domain_color(t: dict, domain: str, soft: bool = False) -> str:
    key = f"dom_{domain if domain in DOMAINS else 'studio'}"
    return t[key + "_soft"] if soft else t[key]


# --------------------------------------------------------------------------- hero

def monogram_mark(x: float, y: float, s: float, t: dict) -> list[str]:
    """Restrained personal mark: rounded plate, tight HSA letters, one accent corner."""
    return [rect(x, y, s, s, t["surface"], rx=s * 0.22, stroke=t["rule"], sw=1.5),
            rect(x + s * 0.14, y + s * 0.14, s * 0.12, s * 0.12, t["accent"], rx=s * 0.03),
            text(x + s * 0.5, y + s * 0.74, "HSA", s * 0.34, t["fg"], weight="700", anchor="middle", spacing=-s * 0.01)]


def _domain_node(x: float, y: float, w: float, h: float, dom: str, label: str, caption: str, t: dict,
                 label_size: float, caption_size: float, glyph_size: float) -> list[str]:
    col = domain_color(t, dom)
    out = [rect(x, y, w, h, t["surface"], rx=12, stroke=t["rule"]),
           rect(x + 18, y + 18, glyph_size + 16, glyph_size + 16, domain_color(t, dom, soft=True), rx=9),
           *glyph(dom, x + 26, y + 26, glyph_size, col)]
    lx = x + 18 + glyph_size + 16 + 16
    out.append(text(lx, y + 26 + glyph_size * 0.62, label, fit_size(label, w - (lx - x) - 14, label_size, "700"), t["fg"], weight="700"))
    out.append(text(x + 18, y + h - 20, caption, fit_size(caption, w - 36, caption_size, floor=16), t["muted"]))
    return out


POSITIONING = "Building operational software across logistics, field service, business automation and autonomous AI systems."


def render_hero(theme: str, mobile: bool = False) -> str:
    t = THEMES[theme]
    title = "Hilmi Salih Altınışık — Software Engineer & Product Builder"
    if not mobile:
        w, h, m = DESKTOP_W, 440, 56
        body = [rect(0.5, 0.5, w - 1, h - 1, "none", rx=18, stroke=t["rule"])]
        body += monogram_mark(m, 48, 60, t)
        body.append(text(m + 78, 86, "HILMI SALIH ALTINIŞIK", 21, t["muted"], mono=True, spacing=3))
        body.append(text(m, 184, "Software Engineer", 60, t["fg"], weight="700", spacing=-1.5))
        body.append(text(m, 246, "& Product Builder", 60, t["fg"], weight="700", spacing=-1.5))
        pos = wrap(POSITIONING, 23, 560)
        body += lines_block(m, 296, pos, 23, t["muted"], 32)
        by = 296 + 32 * len(pos) + 18
        body.append(rect(m, by - 6, 64, 4, t["accent"], rx=2))
        body.append(text(m + 80, by + 1, "ARCHITECTURE → PRODUCT → LAUNCH", 19, t["fg"], mono=True, spacing=2))
        # Product-domain map: one engineer (hub) connected to four operational domains.
        gx, gy, nw, nh, gap = 676, 64, 224, 118, 22
        hub = (gx + nw + gap / 2, gy + nh + gap + 15)
        body.append(text(gx, gy - 18, "PRODUCT DOMAINS", 18, t["muted"], mono=True, spacing=3))
        positions = [(gx, gy), (gx + nw + gap, gy), (gx, gy + nh + gap + 30), (gx + nw + gap, gy + nh + gap + 30)]
        for (dom, label, caption), (nx, ny) in zip(HERO_DOMAINS, positions):
            cx = nx + nw if nx == gx else nx
            cy = ny + nh if ny == gy else ny
            body.append(line(hub[0], hub[1], cx, cy, t["accent2"], 1.5))
        for (dom, label, caption), (nx, ny) in zip(HERO_DOMAINS, positions):
            body += _domain_node(nx, ny, nw, nh, dom, label, caption, t, 22, 18, 26)
        body += [circle(hub[0], hub[1], 22, t["accent"]), circle(hub[0], hub[1], 8, t["bg"])]
    else:
        w, m = MOBILE_W, 36
        body = []
        body += monogram_mark(m, 40, 68, t)
        body.append(text(m + 88, 84, "HILMI SALIH ALTINIŞIK", 22, t["muted"], mono=True, spacing=2.5))
        body.append(text(m, 188, "Software Engineer", 56, t["fg"], weight="700", spacing=-1.5))
        body.append(text(m, 248, "& Product Builder", 56, t["fg"], weight="700", spacing=-1.5))
        pos = wrap(POSITIONING, 27, w - 2 * m)
        body += lines_block(m, 302, pos, 27, t["muted"], 38)
        by = 302 + 38 * len(pos) + 22
        body.append(rect(m, by - 7, 56, 4, t["accent"], rx=2))
        body.append(text(m + 72, by, "ARCHITECTURE → PRODUCT → LAUNCH", 21, t["fg"], mono=True, spacing=1.5))
        gy = by + 60
        body.append(text(m, gy - 18, "PRODUCT DOMAINS", 20, t["muted"], mono=True, spacing=3))
        nw, nh, gap = (w - 2 * m - 40) / 2, 146, 40
        hub = (w / 2, gy + nh + gap / 2)
        positions = [(m, gy), (m + nw + gap, gy), (m, gy + nh + gap), (m + nw + gap, gy + nh + gap)]
        for (dom, label, caption), (nx, ny) in zip(HERO_DOMAINS, positions):
            cx = nx + nw if nx == m else nx
            cy = ny + nh if ny == gy else ny
            body.append(line(hub[0], hub[1], cx, cy, t["accent2"], 1.5))
        for (dom, label, caption), (nx, ny) in zip(HERO_DOMAINS, positions):
            body += _domain_node(nx, ny, nw, nh, dom, label, caption, t, 24, 20, 28)
        body += [circle(hub[0], hub[1], 17, t["accent"]), circle(hub[0], hub[1], 6, t["bg"])]
        h = int(gy + 2 * nh + gap + m)
        body.insert(0, rect(0.5, 0.5, w - 1, h - 1, "none", rx=18, stroke=t["rule"]))
    desc = (f"{'Mobile' if mobile else 'Desktop'} editorial hero: personal monogram, {POSITIONING} "
            "A map connects one engineer to four product domains: " + "; ".join(f"{l} — {c}" for _, l, c in HERO_DOMAINS) + ".")
    return svg(w, h, title, desc, body, t["bg"])


# --------------------------------------------------------------------------- proof (evidence cards)

EVIDENCE_GLYPHS = {"commits_12m": "commits", "repos_contributed_12m": "repositories", "owned_repos": "owned", "verified_collaborations": "collaboration"}


MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def _month(iso: str) -> str:
    """'2025-09-21' -> 'SEP 2025' (falls back to the raw value)."""
    try:
        return f"{MONTHS[int(iso[5:7]) - 1]} {iso[:4]}"
    except (ValueError, IndexError):
        return str(iso)


def _timeline(x1: float, x2: float, y: float, t: dict, footprint: dict, size: float) -> list[str]:
    win = footprint.get("window", {})
    out = [line(x1, y, x2, y, t["rule"], 2), line(x1, y - 8, x1, y + 8, t["accent2"], 2), line(x2, y - 8, x2, y + 8, t["accent2"], 2),
           circle(x2, y, 5, t["accent"]),
           text(x1, y + size + 12, _month(win.get("from", "")), size, t["muted"], mono=True, spacing=1),
           text(x2, y + size + 12, _month(win.get("to", "")), size, t["muted"], mono=True, spacing=1, anchor="end")]
    label = f"MEASURED {footprint.get('measured_on', '')} · GITHUB API · AUTHOR-LOGIN MATCH"
    out.append(text((x1 + x2) / 2, y - 12, label, size, t["muted"], mono=True, spacing=1, anchor="middle"))
    return out


def render_proof(footprint: dict, theme: str, mobile: bool = False) -> str:
    t = THEMES[theme]
    metrics = list(footprint["metrics"][:4])
    if not mobile:
        w, h, m = DESKTOP_W, 304, 48
        cw, ch, gap = (w - 2 * m - 3 * 20) / 4, 168, 20
        body = [rect(0.5, 0.5, w - 1, h - 1, "none", rx=18, stroke=t["rule"]),
                text(m, 36, "VERIFIED ENGINEERING FOOTPRINT", 18, t["muted"], mono=True, spacing=3),
                text(w - m, 36, "12 MONTHS", 18, t["accent"], mono=True, spacing=3, anchor="end")]
        y = 52
        for i, mt in enumerate(metrics):
            x = m + i * (cw + gap)
            body += card(x, y, cw, ch, t)
            body.append(rect(x + 20, y + 20, 44, 44, t["accent_soft"], rx=10))
            body += glyph(EVIDENCE_GLYPHS.get(mt.get("key", ""), "commits"), x + 28, y + 28, 28, t["accent"], t["accent_soft"])
            body.append(text(x + 20, y + 112, format(int(mt["value"]), ","), 58, t["fg"], weight="700", spacing=-1.5))
            body.append(text(x + 20, y + 139, mt["label"], fit_size(mt["label"], cw - 40, 20, "600"), t["fg"], weight="600"))
            body.append(text(x + 20, y + 158, mt.get("note", ""), fit_size(mt.get("note", ""), cw - 40, 17, floor=15), t["muted"]))
        body += _timeline(m + 8, w - m - 8, 258, t, footprint, 16)
    else:
        w, h, m = MOBILE_W, 620, 36
        cw, ch, gap = (w - 2 * m - 24) / 2, 210, 24
        body = [rect(0.5, 0.5, w - 1, h - 1, "none", rx=18, stroke=t["rule"]),
                text(m, 44, "VERIFIED FOOTPRINT", 20, t["muted"], mono=True, spacing=3),
                text(w - m, 44, "12 MONTHS", 20, t["accent"], mono=True, spacing=3, anchor="end")]
        for i, mt in enumerate(metrics):
            x = m + (i % 2) * (cw + gap)
            y = 64 + (i // 2) * (ch + gap)
            body += card(x, y, cw, ch, t)
            body.append(rect(x + 20, y + 20, 48, 48, t["accent_soft"], rx=10))
            body += glyph(EVIDENCE_GLYPHS.get(mt.get("key", ""), "commits"), x + 29, y + 29, 30, t["accent"], t["accent_soft"])
            body.append(text(x + 20, y + 132, format(int(mt["value"]), ","), 56, t["fg"], weight="700", spacing=-1.5))
            label = str(mt.get("short_label") or mt["label"])
            body.append(text(x + 20, y + 164, label, fit_size(label, cw - 40, 24, "600"), t["fg"], weight="600"))
            body.append(text(x + 20, y + 192, mt.get("note", ""), fit_size(mt.get("note", ""), cw - 40, 20, floor=17), t["muted"]))
        body += _timeline(m + 8, w - m - 8, 572, t, footprint, 18)
    window = footprint.get("window", {}).get("label", "")
    summary = "; ".join(f"{int(x['value']):,} {x['label'].lower()}" for x in metrics)
    return svg(w, h, f"Verified engineering footprint · {window}",
               f"{summary}. Measured with the GitHub API on {footprint.get('measured_on', '')}.", body, t["bg"])


# --------------------------------------------------------------------------- flagship diagrams

def _box(x: float, y: float, w: float, h: float, label: str, t: dict, size: float) -> list[str]:
    return [rect(x, y, w, h, t["surface2"], rx=8),
            text(x + 22, y + h / 2 + size * 0.36, label, size, t["fg"])]


def render_flagship(spec: dict, theme: str) -> str:
    t = THEMES[theme]
    w, h, m = DESKTOP_W, 380, 48
    col = domain_color(t, spec.get("domain", "studio"))
    soft = domain_color(t, spec.get("domain", "studio"), soft=True)
    body = [rect(0.5, 0.5, w - 1, h - 1, "none", rx=16, stroke=t["rule"])]
    body.append(text(m, 46, f"FLAGSHIP {spec['index']}", 22, col, mono=True, spacing=3))
    body.append(text(m, 90, spec["name"], 46, t["fg"], weight="700", spacing=-1))
    body.append(text(w - m, 90, spec["label"], 28, t["muted"], anchor="end"))
    body.append(line(m, 110, w - m, 110, t["rule"], 1.5))
    col_gap = 44
    col_w = (w - 2 * m - 2 * col_gap) / 3
    x1, x2, x3 = m, m + col_w + col_gap, m + 2 * (col_w + col_gap)
    top = 142
    body.append(text(x1, top, spec["surfaces_title"].upper(), 22, t["muted"], mono=True, spacing=2))
    body.append(text(x2, top, spec["core_title"].upper(), 22, col, mono=True, spacing=2))
    body.append(text(x3, top, spec["foundation_title"].upper(), 22, t["muted"], mono=True, spacing=2))
    box_h, gap = 60, 14
    y0 = top + 18
    labels = spec["surfaces"][:3] + spec["foundation"][:3] + spec["core"][:3]
    size = min(fit_size(lbl, col_w - 44, 28, "600") for lbl in labels)
    for i, label in enumerate(spec["surfaces"][:3]):
        body += _box(x1, y0 + i * (box_h + gap), col_w, box_h, label, t, size)
    for i, label in enumerate(spec["foundation"][:3]):
        body += _box(x3, y0 + i * (box_h + gap), col_w, box_h, label, t, size)
    core_h = 3 * box_h + 2 * gap
    body.append(rect(x2, y0, col_w, core_h, soft, rx=10))
    body.append(rect(x2, y0, 6, core_h, col, rx=3))
    for i, label in enumerate(spec["core"][:3]):
        body.append(text(x2 + 26, y0 + 42 + i * 66, label, size, t["fg"], weight="600"))
    mid = y0 + core_h / 2
    body.append(line(x1 + col_w, mid, x2, mid, t["accent2"], 2))
    body.append(line(x2 + col_w, mid, x3, mid, t["accent2"], 2))
    body.append(circle(x2, mid, 5, col))
    body.append(circle(x3, mid, 5, col))
    desc = (f"{spec['name']} system diagram. {spec['surfaces_title']}: {', '.join(spec['surfaces'])}. "
            f"{spec['core_title']}: {', '.join(spec['core'])}. {spec['foundation_title']}: {', '.join(spec['foundation'])}.")
    return svg(w, h, f"{spec['name']} — {spec['label']}", desc, body, t["bg"])


# --------------------------------------------------------------------------- product board

def product_cards(portfolio: dict) -> list[dict]:
    """Tier-2 products that are not collaborations, in portfolio order."""
    items = [p for p in portfolio["products"] if p["featured_tier"] == 2 and not p.get("collaboration")]
    return sorted(items, key=lambda p: (p["sort_order"], p["display_name"].lower()))


def collaboration_cards(portfolio: dict) -> list[dict]:
    items = [p for p in portfolio["products"] if p.get("collaboration")]
    return sorted(items, key=lambda p: (p["sort_order"], p["display_name"].lower()))


def _product_card(x: float, y: float, w: float, h: float, p: dict, t: dict, mobile: bool) -> list[str]:
    dom = p.get("domain", "studio")
    col, soft = domain_color(t, dom), domain_color(t, dom, soft=True)
    gs = 34 if mobile else 30
    cat_s, name_s, pos_s, stack_s, meta_s = (22, 34, 27, 23, 22) if mobile else (18, 30, 22, 19, 18)
    out = card(x, y, w, h, t, accent=col)
    out.append(rect(x + 30, y + 26, gs + 22, gs + 22, soft, rx=11))
    out += glyph(p.get("icon", "system-map"), x + 41, y + 37, gs, col, soft)
    tx = x + 30 + gs + 22 + 20
    out.append(text(tx, y + 26 + 18, str(p.get("category", "")).upper(), cat_s, col, mono=True, spacing=2))
    out.append(text(tx, y + 26 + 18 + name_s + 6, p["display_name"], fit_size(p["display_name"], w - (tx - x) - 26, name_s, "700", floor=22), t["fg"], weight="700", spacing=-0.5))
    py = y + 26 + gs + 22 + 40
    lines = wrap(p.get("short_summary") or p["tagline"], pos_s, w - 60, max_lines=2)
    out += lines_block(x + 30, py, lines, pos_s, t["fg"], pos_s * 1.35)
    sy = py + pos_s * 1.35 * 2 + 8
    stack = " · ".join(p["stack"])
    out.append(text(x + 30, sy, stack, fit_size(stack, w - 60, stack_s, floor=15), t["muted"]))
    out.append(line(x + 30, y + h - 44, x + w - 30, y + h - 44, t["rule"], 1))
    meta = f"{p['status']}  ·  {p['access']}  ·  {p['role']}"
    out.append(text(x + 30, y + h - 18, meta, fit_size(meta, w - 60, meta_s, floor=15), t["muted"]))
    return out


def render_ecosystem(portfolio: dict, theme: str, mobile: bool = False) -> str:
    t = THEMES[theme]
    items = product_cards(portfolio)
    if not mobile:
        w, m, cols, cw, ch, gap = DESKTOP_W, 40, 2, (DESKTOP_W - 80 - 24) / 2, 236, 24
    else:
        w, m, cols, cw, ch, gap = MOBILE_W, 32, 1, MOBILE_W - 64, 318, 22
    rows = (len(items) + cols - 1) // cols
    h = m + rows * ch + (rows - 1) * gap + m
    body = [rect(0.5, 0.5, w - 1, h - 1, "none", rx=18, stroke=t["rule"])]
    for i, p in enumerate(items):
        x = m + (i % cols) * (cw + gap)
        y = m + (i // cols) * (ch + gap)
        body += _product_card(x, y, cw, ch, p, t, mobile)
    names = ", ".join(p["display_name"] for p in items)
    desc = "Product board: " + "; ".join(f"{p['display_name']} ({p.get('category', '')}) — {p.get('short_summary') or p['tagline']} {p['status']}, {p['access']}, {p['role']}" for p in items)
    return svg(w, int(h), f"Selected product ecosystem — {names}", desc, body, t["bg"])


# --------------------------------------------------------------------------- collaboration board

def _collab_card(x: float, y: float, w: float, h: float, p: dict, t: dict, mobile: bool) -> list[str]:
    c = p["collaboration"]
    gs = 36 if mobile else 32
    lab_s, name_s, pos_s, ev_s, meta_s, role_s = (20, 34, 26, 44, 21, 20) if mobile else (16, 30, 22, 40, 17, 16)
    out = card(x, y, w, h, t, accent=t["accent"])
    out.append(rect(x + 30, y + 26, gs + 22, gs + 22, t["accent_soft"], rx=11))
    out += glyph("collaboration", x + 41, y + 37, gs, t["accent"], t["accent_soft"])
    tx = x + 30 + gs + 22 + 20
    out.append(text(tx, y + 26 + 18, str(c.get("label", "Built in collaboration")).upper(), lab_s, t["muted"], mono=True, spacing=2))
    out.append(text(tx, y + 26 + 18 + name_s + 6, p["display_name"], fit_size(p["display_name"], w - (tx - x) - 26, name_s, "700", floor=22), t["fg"], weight="700", spacing=-0.5))
    py = y + 26 + gs + 22 + 40
    lines = wrap(p.get("short_summary") or p["tagline"], pos_s, w - 60, max_lines=2)
    out += lines_block(x + 30, py, lines, pos_s, t["fg"], pos_s * 1.35)
    out.append(line(x + 30, y + h - 92, x + w - 30, y + h - 92, t["rule"], 1))
    # Evidence row: verified counts left, role chip right; access label underneath.
    ey = y + h - 46
    role = str(p["role"]).upper()
    rw = text_width(role, role_s, mono=True) + 28
    out.append(text(x + 30, ey, c["evidence"], fit_size(c["evidence"], w - 60 - rw - 24, ev_s, "700", floor=26), t["fg"], weight="700", spacing=-1))
    out.append(rect(x + w - 30 - rw, ey - role_s - 12, rw, role_s + 16, t["accent_soft"], rx=(role_s + 16) / 2))
    out.append(text(x + w - 30 - rw / 2, ey - 1, role, role_s, t["accent"], mono=True, spacing=1.5, anchor="middle"))
    meta = f"{p['status']}  ·  {p['access']}"
    out.append(text(x + 30, y + h - 18, meta, fit_size(meta, w - 60, meta_s, floor=15), t["muted"]))
    return out


def render_collaborations(portfolio: dict, theme: str, mobile: bool = False) -> str:
    t = THEMES[theme]
    items = collaboration_cards(portfolio)
    if not mobile:
        w, m, cols, cw, ch, gap = DESKTOP_W, 40, 2, (DESKTOP_W - 80 - 24) / 2, 252, 24
    else:
        w, m, cols, cw, ch, gap = MOBILE_W, 32, 1, MOBILE_W - 64, 320, 22
    rows = (len(items) + cols - 1) // cols
    h = m + rows * ch + (rows - 1) * gap + m
    body = [rect(0.5, 0.5, w - 1, h - 1, "none", rx=18, stroke=t["rule"])]
    for i, p in enumerate(items):
        x = m + (i % cols) * (cw + gap)
        y = m + (i // cols) * (ch + gap)
        body += _collab_card(x, y, cw, ch, p, t, mobile)
    names = ", ".join(p["display_name"] for p in items)
    desc = "Verified collaborations on partner-owned products: " + "; ".join(
        f"{p['display_name']} — {p['role']}, {p['collaboration']['evidence']}, {p['status']}, {p['access']}" for p in items)
    return svg(w, int(h), f"Selected collaborations — {names}", desc, body, t["bg"])


# --------------------------------------------------------------------------- engineering approach

def render_approach(theme: str, mobile: bool = False) -> str:
    t = THEMES[theme]
    if not mobile:
        w, h, m = DESKTOP_W, 304, 48
        cw = (w - 2 * m) / len(APPROACH)
        body = [rect(0.5, 0.5, w - 1, h - 1, "none", rx=18, stroke=t["rule"])]
        cy = 104
        body.append(line(m + cw / 2, cy, w - m - cw / 2, cy, t["rule"], 2))
        for i, (key, title, sub) in enumerate(APPROACH):
            cx = m + cw * (i + 0.5)
            body.append(circle(cx, cy, 34, t["surface"], t["accent"], 2))
            body += glyph(key, cx - 16, cy - 16, 32, t["accent"])
            body.append(text(cx, 48, f"0{i + 1}", 17, t["muted"], mono=True, spacing=2, anchor="middle"))
            body.append(text(cx, 178, title, fit_size(title, cw - 16, 23, "700"), t["fg"], weight="700", anchor="middle"))
            lines = wrap(sub, 18, cw - 20, max_lines=3)
            body += lines_block(cx, 208, lines, 18, t["muted"], 24, anchor="middle")
        body.append(text(w / 2, 282, "ARCHITECTURE  →  PRODUCT  →  LAUNCH", 16, t["accent2"], mono=True, spacing=3, anchor="middle"))
    else:
        w, m, step = MOBILE_W, 36, 168
        h = 60 + step * len(APPROACH) + 20
        body = [rect(0.5, 0.5, w - 1, h - 1, "none", rx=18, stroke=t["rule"])]
        sx = m + 40
        body.append(line(sx, 70, sx, 60 + step * (len(APPROACH) - 1) + 40, t["rule"], 2))
        for i, (key, title, sub) in enumerate(APPROACH):
            cy = 60 + step * i + 40
            body.append(circle(sx, cy, 34, t["surface"], t["accent"], 2))
            body += glyph(key, sx - 16, cy - 16, 32, t["accent"])
            tx = sx + 62
            body.append(text(tx, cy - 22, f"0{i + 1}", 19, t["muted"], mono=True, spacing=2))
            body.append(text(tx, cy + 8, title, fit_size(title, w - tx - m, 30, "700"), t["fg"], weight="700"))
            lines = wrap(sub, 24, w - tx - m, max_lines=3)
            body += lines_block(tx, cy + 42, lines, 24, t["muted"], 30)
    desc = "Engineering approach in five stages: " + "; ".join(f"{ti} — {s}" for _, ti, s in APPROACH)
    return svg(w, h, "Engineering approach — five stages from architecture to observation", desc, body, t["bg"])


# --------------------------------------------------------------------------- entry points

def asset_path(name: str, theme: str, asset_dir: str = ASSET_DIR) -> str:
    return os.path.join(asset_dir, f"{name}-{theme}.svg")


RESPONSIVE_ASSETS = ("hero", "proof", "ecosystem", "collaborations", "approach")


def render_all(footprint: dict, portfolio: dict) -> dict[str, str]:
    """Return {relative path: svg text} for every V5 asset."""
    out: dict[str, str] = {}
    for theme in THEMES:
        out[asset_path("hero-desktop", theme)] = render_hero(theme)
        out[asset_path("hero-mobile", theme)] = render_hero(theme, mobile=True)
        out[asset_path("proof-desktop", theme)] = render_proof(footprint, theme)
        out[asset_path("proof-mobile", theme)] = render_proof(footprint, theme, mobile=True)
        for pid, spec in FLAGSHIPS.items():
            out[asset_path(f"flagship-{pid}", theme)] = render_flagship(spec, theme)
        out[asset_path("ecosystem-desktop", theme)] = render_ecosystem(portfolio, theme)
        out[asset_path("ecosystem-mobile", theme)] = render_ecosystem(portfolio, theme, mobile=True)
        out[asset_path("collaborations-desktop", theme)] = render_collaborations(portfolio, theme)
        out[asset_path("collaborations-mobile", theme)] = render_collaborations(portfolio, theme, mobile=True)
        out[asset_path("approach-desktop", theme)] = render_approach(theme)
        out[asset_path("approach-mobile", theme)] = render_approach(theme, mobile=True)
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
    parser.add_argument("--portfolio", default=os.path.join("data", "portfolio.json"))
    parser.add_argument("--prune", action="store_true", help="delete SVGs in the asset directory that are no longer rendered")
    args = parser.parse_args(argv)
    with open(args.footprint, encoding="utf-8") as fh:
        footprint = json.load(fh)
    with open(args.portfolio, encoding="utf-8") as fh:
        portfolio = json.load(fh)
    rendered = render_all(footprint, portfolio)
    changed = [p for p, content in rendered.items() if write_if_changed(p, content)]
    if args.prune:
        keep = {os.path.basename(p) for p in rendered}
        for name in sorted(os.listdir(ASSET_DIR)):
            if name.endswith(".svg") and name not in keep:
                os.remove(os.path.join(ASSET_DIR, name))
                changed.append(f"removed {name}")
    print(f"render-assets: {len(changed)} file(s) written" + (": " + ", ".join(changed) if changed else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
