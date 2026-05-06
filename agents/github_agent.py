# agents/github_agent.py
import os
import logging
from datetime import datetime, timezone

import httpx

logger = logging.getLogger("jarvis.github")

GITHUB_USER = "phiman13"
REPOS = ["recipe-app", "herrlich-ai-platform", "immo-radar", "refurbish-business", "herrlich-dev"]
_API = "https://api.github.com"


def _headers() -> dict:
    token = os.environ.get("GITHUB_TOKEN", "")
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _format_age(created_at: str) -> str:
    try:
        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        days = (datetime.now(timezone.utc) - dt).days
        if days == 0:
            return "heute"
        return f"{days}d"
    except Exception:
        return "?"


def get_github_summary() -> str:
    try:
        open_prs = []
        for repo in REPOS:
            resp = httpx.get(
                f"{_API}/repos/{GITHUB_USER}/{repo}/pulls?state=open&per_page=5",
                headers=_headers(), timeout=10,
            )
            resp.raise_for_status()
            for pr in resp.json():
                open_prs.append(f"• {repo}: \"{pr['title']}\" — {_format_age(pr['created_at'])} offen")

        lines = []
        if open_prs:
            lines.append(f"💻 GITHUB ({len(open_prs)} offene PRs)")
            lines.extend(open_prs[:5])
        else:
            lines.append("💻 GITHUB — keine offenen PRs")
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"GitHub nicht verfügbar: {e}")
        return "💻 GITHUB nicht verfügbar"
