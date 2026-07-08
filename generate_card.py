#!/usr/bin/env python3
"""
Generates a PageSpeed-Insights-style circular gauge SVG card showing
live GitHub profile stats. Meant to be run on a schedule via GitHub
Actions so the image commits itself and stays up to date.

Metrics shown (each as a ring):
  - Public Repositories   (progress toward a goal of 50)
  - Followers             (progress toward a goal of 200)
  - Total Stars Earned    (progress toward a goal of 100)
  - Contributions (year)  (progress toward a goal of 1000)

IMPORTANT — token requirements:
  - Repositories / Followers / Stars are fetched via the plain REST API.
    These are public endpoints and work fine with the automatic
    `secrets.GITHUB_TOKEN` GitHub Actions provides.
  - Contributions (the yearly commit-calendar total) can ONLY be read via
    GraphQL's `contributionsCollection` field, and the automatic
    GITHUB_TOKEN is not reliably authorized for that field. You must add
    a classic Personal Access Token with the `read:user` scope as a repo
    secret named STATS_TOKEN (Settings -> Secrets and variables -> Actions
    -> New repository secret). Without it, the contributions ring will
    show 0 rather than silently guessing.

Usage:
  GITHUB_TOKEN=xxxx STATS_TOKEN=yyyy GITHUB_USERNAME=ganesh123381 python generate_card.py
Output:
  profile-card.svg  (written to the current directory)
"""

import os
import math
import sys
import requests

USERNAME = os.environ.get("GITHUB_USERNAME", "ganesh123381")
# Prefer a dedicated PAT (STATS_TOKEN) for GraphQL; fall back to the
# automatic Actions token for the REST calls that don't need extra scope.
REST_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GRAPHQL_TOKEN = os.environ.get("STATS_TOKEN") or REST_TOKEN

GOALS = {
    "repos": 50,
    "followers": 200,
    "stars": 100,
    "contributions": 1000,
}

REST_HEADERS = {"Accept": "application/vnd.github+json"}
if REST_TOKEN:
    REST_HEADERS["Authorization"] = f"Bearer {REST_TOKEN}"

CONTRIB_QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar { totalContributions }
    }
  }
}
"""


def fetch_profile_counts():
    """Followers + public repo count, straight from the REST user endpoint —
    this matches exactly what's shown on the profile page."""
    resp = requests.get(
        f"https://api.github.com/users/{USERNAME}",
        headers=REST_HEADERS,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["followers"], data["public_repos"]


def fetch_total_stars():
    """Sum stargazers across ALL owned repos (forks included, matching the
    profile's Repositories tab), paginated."""
    total_stars = 0
    page = 1
    while True:
        resp = requests.get(
            f"https://api.github.com/users/{USERNAME}/repos",
            headers=REST_HEADERS,
            params={"per_page": 100, "page": page, "type": "owner"},
            timeout=15,
        )
        resp.raise_for_status()
        repos = resp.json()
        if not repos:
            break
        total_stars += sum(r.get("stargazers_count", 0) for r in repos)
        if len(repos) < 100:
            break
        page += 1
    return total_stars


def fetch_contributions():
    """Yearly contribution total via GraphQL. Requires STATS_TOKEN (a PAT
    with read:user scope) — returns 0 with a warning if unavailable rather
    than guessing."""
    if not GRAPHQL_TOKEN:
        print("Warning: no token available for contributions query; using 0.", file=sys.stderr)
        return 0
    try:
        resp = requests.post(
            "https://api.github.com/graphql",
            json={"query": CONTRIB_QUERY, "variables": {"login": USERNAME}},
            headers={"Authorization": f"bearer {GRAPHQL_TOKEN}"},
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
        if "errors" in payload:
            print(f"Warning: GraphQL errors: {payload['errors']}", file=sys.stderr)
            return 0
        return payload["data"]["user"]["contributionsCollection"]["contributionCalendar"]["totalContributions"]
    except Exception as e:
        print(f"Warning: contributions fetch failed ({e}); using 0. "
              f"Add a STATS_TOKEN repo secret (PAT with read:user scope) to fix this.", file=sys.stderr)
        return 0


def fetch_stats():
    followers, repos = fetch_profile_counts()
    stars = fetch_total_stars()
    contributions = fetch_contributions()
    return {
        "repos": repos,
        "followers": followers,
        "stars": stars,
        "contributions": contributions,
    }


def score_color(pct):
    if pct >= 90:
        return "#0cce6b"   # green
    if pct >= 50:
        return "#ffa400"   # orange
    return "#ff4e42"       # red


def ring(cx, cy, r, pct, color, stroke_width=8):
    circumference = 2 * math.pi * r
    offset = circumference * (1 - pct / 100)
    return f'''
    <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#2a2f3a" stroke-width="{stroke_width}"/>
    <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" stroke-width="{stroke_width}"
      stroke-linecap="round" stroke-dasharray="{circumference:.2f}" stroke-dashoffset="{offset:.2f}"
      transform="rotate(-90 {cx} {cy})"/>
    '''


def build_svg(stats, username):
    card_w, card_h = 760, 260
    metrics = [
        ("Repositories", stats["repos"], GOALS["repos"]),
        ("Followers", stats["followers"], GOALS["followers"]),
        ("Total Stars", stats["stars"], GOALS["stars"]),
        ("Contributions (yr)", stats["contributions"], GOALS["contributions"]),
    ]

    n = len(metrics)
    gap = card_w / n
    r = 42
    cy = 150

    circles_svg = ""
    for i, (label, value, goal) in enumerate(metrics):
        pct = min(100, round((value / goal) * 100)) if goal else 0
        color = score_color(pct)
        cx = gap * i + gap / 2
        circles_svg += ring(cx, cy, r, pct, color)
        circles_svg += f'''
        <text x="{cx}" y="{cy+8}" text-anchor="middle" font-family="'Segoe UI', Arial, sans-serif"
          font-size="26" font-weight="700" fill="{color}">{value}</text>
        <text x="{cx}" y="{cy+r+34}" text-anchor="middle" font-family="'Segoe UI', Arial, sans-serif"
          font-size="14" fill="#c9d1d9">{label}</text>
        '''

    svg = f'''<svg width="{card_w}" height="{card_h}" viewBox="0 0 {card_w} {card_h}"
  xmlns="http://www.w3.org/2000/svg">
  <defs>
    <clipPath id="rounded">
      <rect x="0" y="0" width="{card_w}" height="{card_h}" rx="18" ry="18"/>
    </clipPath>
  </defs>
  <g clip-path="url(#rounded)">
    <rect width="{card_w}" height="{card_h}" fill="#0d1117"/>
    <rect x="0" y="0" width="{card_w}" height="4" fill="url(#accent)"/>
    <defs>
      <linearGradient id="accent" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0%" stop-color="#00f7ff"/>
        <stop offset="100%" stop-color="#7b2ff7"/>
      </linearGradient>
    </defs>
    <text x="30" y="42" font-family="'Segoe UI', Arial, sans-serif" font-size="20" font-weight="700" fill="#ffffff">
      🚀 GitHub Profile Insights
    </text>
    <text x="30" y="66" font-family="'Segoe UI', Arial, sans-serif" font-size="13" fill="#8b949e">
      github.com/{username} · auto-updated
    </text>
    {circles_svg}
  </g>
  <rect x="0.5" y="0.5" width="{card_w-1}" height="{card_h-1}" rx="18" ry="18" fill="none" stroke="#30363d"/>
</svg>'''
    return svg


def main():
    try:
        stats = fetch_stats()
    except Exception as e:
        print(f"Warning: live fetch failed ({e}); writing placeholder card.", file=sys.stderr)
        stats = {"repos": 0, "followers": 0, "stars": 0, "contributions": 0}

    svg = build_svg(stats, USERNAME)
    with open("profile-card.svg", "w") as f:
        f.write(svg)
    print("Wrote profile-card.svg with stats:", stats)


if __name__ == "__main__":
    main()
