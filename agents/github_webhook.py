"""GitHub Webhook handler — auto-deploy on push events."""

import hashlib
import hmac
import json
import logging
import os
import subprocess

from fastapi import HTTPException, Request
from telegram import Bot

import app_state

logger = logging.getLogger("jarvis.github_webhook")

# git_path: wo git pull läuft
# post_rsync: (src, dst) — nach pull synchron rsync-en
# post_docker: workdir für "docker compose up -d --build" (async, Popen)
# post_restart: systemd-Servicename, der neu gestartet wird (3s Verzögerung)
_GITHUB_REPOS: dict[str, dict] = {
    "herrlich-ai-platform": {
        "git_path": "/opt/herrlich-ai-platform",
        "post_rsync": ("/opt/herrlich-ai-platform/agents/", "/opt/jarvis/"),
        "post_restart": "jarvis",
    },
    "high-five-website": {
        "git_path": "/opt/high-five-website",
        "post_docker": "/opt/high-five-website",
    },
    "immo-radar": {
        "git_path": "/opt/immo-radar",
        "post_docker": "/opt/immo-radar",
    },
    "refurbish-business": {
        "git_path": "/opt/refurbish-business",
        "post_docker": "/opt/refurbish-business",
    },
}


async def github_webhook(request: Request):
    body = await request.body()

    webhook_secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
    if webhook_secret:
        sig_header = request.headers.get("X-Hub-Signature-256", "")
        expected = (
            "sha256="
            + hmac.new(webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        )
        if not hmac.compare_digest(sig_header, expected):
            raise HTTPException(status_code=403, detail="Invalid signature")

    event_type = request.headers.get("X-GitHub-Event", "")
    if event_type != "push":
        return {"ok": True, "skipped": "not a push event"}

    try:
        data = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    ref = data.get("ref", "")
    repo_name = data.get("repository", {}).get("name", "")

    if ref not in ("refs/heads/main", "refs/heads/master"):
        return {"ok": True, "skipped": f"branch {ref} ignored"}

    repo_cfg = _GITHUB_REPOS.get(repo_name)
    if not repo_cfg or not os.path.isdir(repo_cfg["git_path"]):
        return {"ok": True, "skipped": f"repo {repo_name!r} not configured"}

    try:
        # fetch + reset --hard statt pull --ff-only: blockiert nicht bei lokalen Änderungen
        git_path = repo_cfg["git_path"]
        subprocess.run(
            ["git", "-C", git_path, "fetch", "origin"],
            capture_output=True,
            timeout=30,
        )
        branch = "main"
        result = subprocess.run(
            ["git", "-C", git_path, "reset", "--hard", f"origin/{branch}"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        success = result.returncode == 0
        output = (result.stdout + result.stderr).strip()[:300]

        # Fallback: Dateien mit falscher UID (z.B. 501 von root-rsync) blockieren jarvis.
        # Sudoers erlaubt jarvis sudo git für alle konfigurierten Repos → root kann alles überschreiben.
        if not success and (
            "Permission denied" in output or "dubious ownership" in output
        ):
            logger.warning(
                "GitHub webhook: %s reset permission denied, retry as root", repo_name
            )
            subprocess.run(
                ["sudo", "/usr/bin/git", "-C", git_path, "fetch", "origin"],
                capture_output=True,
                timeout=30,
            )
            result = subprocess.run(
                [
                    "sudo",
                    "/usr/bin/git",
                    "-C",
                    git_path,
                    "reset",
                    "--hard",
                    f"origin/{branch}",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            success = result.returncode == 0
            output = (result.stdout + result.stderr).strip()[:300]
    except Exception as e:
        success = False
        output = str(e)

    already_up = "already up to date" in output.lower()

    if success and not already_up:
        if "post_rsync" in repo_cfg:
            src, dst = repo_cfg["post_rsync"]
            subprocess.run(
                [
                    "rsync",
                    "-a",
                    "--delete",
                    "--exclude=venv",
                    "--exclude=__pycache__",
                    "--exclude=*.pyc",
                    src,
                    dst,
                ],
                capture_output=True,
                timeout=30,
            )
        if "post_docker" in repo_cfg:
            subprocess.Popen(
                ["docker", "compose", "up", "-d", "--build"],
                cwd=repo_cfg["post_docker"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        if "post_restart" in repo_cfg:
            subprocess.Popen(
                [
                    "bash",
                    "-c",
                    f"sleep 3 && systemctl restart {repo_cfg['post_restart']}",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    chat_id_str = os.environ.get("TELEGRAM_CHAT_ID", "")
    if chat_id_str:
        try:
            bot = Bot(token=app_state.TELEGRAM_TOKEN)
            status = "✅" if success else "❌"
            if not already_up:
                await bot.send_message(
                    chat_id=int(chat_id_str),
                    text=f"{status} GitHub Push: *{repo_name}*\n`{output}`",
                    parse_mode="Markdown",
                )
        except Exception:
            pass

    logger.info(
        "GitHub webhook: %s pull %s: %s",
        repo_name,
        "ok" if success else "failed",
        output,
    )
    return {"ok": True, "repo": repo_name, "pulled": success, "output": output}
