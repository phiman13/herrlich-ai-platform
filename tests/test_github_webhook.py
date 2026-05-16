# tests/test_github_webhook.py
import asyncio
import hashlib
import hmac
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from github_webhook import github_webhook

_SECRET = "testsecret"


def _make_request(body: bytes, headers: dict):
    req = MagicMock()
    req.body = AsyncMock(return_value=body)
    req.headers = headers  # plain dict — .get() works like Headers
    return req


def _sign(body: bytes, secret: str = _SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _push_body(repo="immo-radar", ref="refs/heads/main") -> bytes:
    return json.dumps({"ref": ref, "repository": {"name": repo}}).encode()


def test_invalid_signature_rejected():
    body = _push_body()
    req = _make_request(
        body, {"X-Hub-Signature-256": "sha256=deadbeef", "X-GitHub-Event": "push"}
    )
    with patch.dict(os.environ, {"GITHUB_WEBHOOK_SECRET": _SECRET}):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(github_webhook(req))
    assert exc.value.status_code == 403


def test_missing_signature_rejected_when_secret_set():
    body = _push_body()
    req = _make_request(body, {"X-GitHub-Event": "push"})
    with patch.dict(os.environ, {"GITHUB_WEBHOOK_SECRET": _SECRET}):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(github_webhook(req))
    assert exc.value.status_code == 403


def test_no_secret_skips_validation():
    """Ohne GITHUB_WEBHOOK_SECRET findet keine Signaturprüfung statt."""
    body = _push_body(repo="not-configured")
    req = _make_request(body, {"X-GitHub-Event": "push"})
    with patch.dict(os.environ, {"GITHUB_WEBHOOK_SECRET": ""}):
        result = asyncio.run(github_webhook(req))
    # kein 403 (kein HTTPException) — der Request lief bis zum Repo-Skip durch
    assert result["ok"] is True
    assert result["skipped"].startswith("repo")


def test_valid_signature_processes_push():
    body = _push_body(repo="immo-radar")
    req = _make_request(
        body, {"X-Hub-Signature-256": _sign(body), "X-GitHub-Event": "push"}
    )
    with (
        patch.dict(
            os.environ, {"GITHUB_WEBHOOK_SECRET": _SECRET, "TELEGRAM_CHAT_ID": ""}
        ),
        patch("os.path.isdir", return_value=True),
        patch(
            "subprocess.run",
            return_value=MagicMock(returncode=0, stdout="Updated", stderr=""),
        ),
        patch("subprocess.Popen"),
    ):
        result = asyncio.run(github_webhook(req))
    assert result["ok"] is True
    assert result["repo"] == "immo-radar"
    assert result["pulled"] is True


def test_non_push_event_skipped():
    body = _push_body()
    req = _make_request(
        body, {"X-Hub-Signature-256": _sign(body), "X-GitHub-Event": "ping"}
    )
    with patch.dict(os.environ, {"GITHUB_WEBHOOK_SECRET": _SECRET}):
        result = asyncio.run(github_webhook(req))
    assert result.get("skipped")
