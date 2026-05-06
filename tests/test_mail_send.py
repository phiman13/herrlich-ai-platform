# tests/test_mail_send.py
import pytest
from unittest.mock import patch, MagicMock
import requests


def test_send_mail_posts_to_graph():
    """MailAgent.send_mail() POSTs to /me/sendMail with correct payload."""
    from agents.mail_agent import MailAgent

    agent = MailAgent()

    mock_response = MagicMock()
    mock_response.status_code = 202
    mock_response.raise_for_status = MagicMock()

    with patch("agents.mail_agent.get_access_token", return_value="tok"), \
         patch("requests.post", return_value=mock_response) as mock_post:
        result = agent.send_mail(
            to_email="anna@beispiel.de",
            subject="Test",
            body="Hallo Anna, das ist ein Test.",
        )

    assert result is True
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
    assert payload["message"]["subject"] == "Test"
    assert payload["message"]["toRecipients"][0]["emailAddress"]["address"] == "anna@beispiel.de"
    assert "Hallo Anna" in payload["message"]["body"]["content"]


def test_send_mail_returns_false_on_error():
    """MailAgent.send_mail() returns False when Graph API raises error."""
    from agents.mail_agent import MailAgent

    agent = MailAgent()

    mock_response = MagicMock()
    mock_response.status_code = 403
    mock_response.raise_for_status = MagicMock(side_effect=requests.HTTPError("403"))

    with patch("agents.mail_agent.get_access_token", return_value="tok"), \
         patch("requests.post", return_value=mock_response):
        result = agent.send_mail("anna@beispiel.de", "Test", "Body")

    assert result is False
