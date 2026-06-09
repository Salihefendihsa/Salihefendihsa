#!/usr/bin/env python3
import os, json, datetime, urllib.request

USER = os.environ.get("GH_USER", "Salihefendihsa")
DAYS = 31
OUT = os.environ.get("OUT", "dist/activity-graph.svg")

def fetch_live():
    token = os.environ["GH_TOKEN"]
    today = datetime.date.today()
    frm = (today - datetime.timedelta(days=DAYS - 1)).isoformat() + "T00:00:00Z"
    to = today.isoformat() + "T23:59:59Z"
    q = {
        "query": """
        query($u:String!,$f:DateTime!,$t:DateTime!){
          user(login:$u){ contributionsCollection(from:$f,to:$t){
            contributionCalendar{ weeks{ contributionDays{ date contributionCount } } }
          }}}""",
        "variables": {"u": USER, "f": frm, "t": to},
    }
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps(q).encode(),
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json"},
    )
    data = json.load(urllib.request.urlopen(req))
    days = []
    for w in data["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]:
        for d in w["contributionDays"]:
            days.append((d["date"], d["contributionCount"]))
    days.sort()
    return days[-DAYS:]

def build(days):
    import math
    W, H = 900, 300
    L, R, T, B = 52, 24, 56, 44
    pw, ph = W - L - R, H - T - B
    counts = [c for _, c in days]
    mx = max(counts) or 1
    n = len(days)
    xs = [L + (pw * i / (n - 1)) for i in range(n)]
    ys = [T + ph - (ph * c / mx) for c in counts]
    base_y = T + ph
    line_d = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in zip(xs, ys))
    area_d = f"M{xs[0]:.1f} {base_y:.1f} L" + " L".join(f"{x:.1f} {y:.1f}" for x, y in zip(xs, ys)) + f" L{xs[-1]:.1f} {base_y:.1f} Z"
    plen = sum(math.dist((xs[i], ys[i]), (xs[i+1], ys[i+1])) for i in range(n-1)) + 1
    grid = []
    for k in range(5):
        gy = T + ph - ph * k / 4
        val = round(mx * k / 4)
        grid.append(f'<line x1="{L}" y1="{gy:.1f}" x2="{W-R}" y2="{gy:.1f}" stroke="#1B2330" stroke-width="1"/>')
        grid.append(f'<text x="{L-8}" y="{gy+4:.1f}" text-anchor="end" font-size="11" fill="#5b6675" font-family="monospace">{val}</text>')
    grid = "\n  ".join(grid)
    xlab = []
    for i in range(0, n, 5):
        d = days[i][0][-2:]
        xlab.append(f'<text x="{xs[i]:.1f}" y="{base_y+22:.0f}" text-anchor="middle" font-size="11" fill="#5b6675" font-family="monospace">{int(d)}</text>')
    xlab = "\n  ".join(xlab)
    dots = []
    for x, y in zip(xs, ys):
        dots.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.4" fill="#A371F7"><animate attributeName="r" values="2;3.5;2" dur="2.4s" repeatCount="indefinite"/><animate attributeName="opacity" values="0.5;1;0.5" dur="2.4s" repeatCount="indefinite"/></circle>')
    dots = "\n  ".join(dots)
    total = sum(counts)
    return f'''<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="contribution activity">
  <defs>
    <linearGradient id="ag_bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0D1117"/><stop offset="1" stop-color="#090C12"/></linearGradient>
    <linearGradient id="ag_line" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#1F6FEB"/><stop offset="1" stop-color="#A371F7"/></linearGradient>
    <linearGradient id="ag_area" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7C5CFF" stop-opacity="0.45"/><stop offset="1" stop-color="#7C5CFF" stop-opacity="0"/></linearGradient>
    <pattern id="ag_dots" width="34" height="34" patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r="1.4" fill="#161C26"/></pattern>
    <filter id="ag_glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="3" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  </defs>
  <rect width="{W}" height="{H}" rx="16" fill="url(#ag_bg)"/>
  <rect width="{W}" height="{H}" rx="16" fill="url(#ag_dots)"/>
  <text x="{L}" y="30" font-size="15" font-weight="700" fill="#F0F6FC" font-family="'Segoe UI',sans-serif">Contribution Activity</text>
  <text x="{W-R}" y="30" text-anchor="end" font-size="13" fill="#8B949E" font-family="monospace">last {DAYS} days · {total} contributions</text>
  {grid}
  {xlab}
  <path d="{area_d}" fill="url(#ag_area)" opacity="0">
    <animate attributeName="opacity" values="0;1" dur="1.6s" begin="0.3s" fill="freeze"/>
  </path>
  <path id="line" d="{line_d}" fill="none" stroke="url(#ag_line)" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="{plen:.0f}" stroke-dashoffset="{plen:.0f}">
    <animate attributeName="stroke-dashoffset" from="{plen:.0f}" to="0" dur="2.6s" begin="0.3s" fill="freeze"/>
  </path>
  {dots}
  <circle r="5" fill="#ffffff" filter="url(#ag_glow)">
    <animateMotion dur="5.2s" repeatCount="indefinite" path="{line_d}"/>
    <animate attributeName="opacity" values="0.4;1;0.4" dur="2s" repeatCount="indefinite"/>
  </circle>
</svg>'''

def main():
    days = fetch_live()
    svg = build(days)
    d = os.path.dirname(OUT)
    if d: os.makedirs(d, exist_ok=True)
    open(OUT, "w").write(svg)
    print(f"wrote {OUT} ({len(svg)} bytes), {len(days)} days")

if __name__ == "__main__":
    main()
