# tests/test_mail_write.py
import pytest
import requests as _requests
from unittest.mock import patch, MagicMock


@pytest.fixture
def agent():
    from agents.mail_agent import MailAgent

    return MailAgent()


def _ok(status=200):
    r = MagicMock()
    r.status_code = status
    r.raise_for_status = MagicMock()
    return r


def _err(status=403):
    def raise_error():
        raise _requests.HTTPError(str(status))

    r = MagicMock()
    r.status_code = status
    r.text = "Error"
    r.raise_for_status = MagicMock(side_effect=raise_error)
    return r


# --- get_mail_body ---


class TestGetMailBody:
    def test_strips_html_tags(self, agent):
        mock_data = {
            "id": "mail123",
            "subject": "Test Subject",
            "from": {"emailAddress": {"name": "Anna", "address": "anna@x.com"}},
            "receivedDateTime": "2026-05-08T10:00:00Z",
            "body": {"contentType": "html", "content": "<p>Hello <b>World</b></p>"},
        }
        with (
            patch("agents.mail_agent.get_access_token", return_value="tok"),
            patch(
                "requests.get",
                return_value=MagicMock(status_code=200, json=lambda: mock_data),
            ),
        ):
            result = agent.get_mail_body("mail123")
        assert result["subject"] == "Test Subject"
        assert result["sender_name"] == "Anna"
        assert result["sender_email"] == "anna@x.com"
        assert "<" not in result["body_text"]
        assert "Hello" in result["body_text"]
        assert "World" in result["body_text"]

    def test_returns_empty_body_text_if_no_body(self, agent):
        mock_data = {
            "id": "mail999",
            "subject": "No body",
            "from": {"emailAddress": {"name": "X", "address": "x@x.com"}},
            "receivedDateTime": "2026-05-08T10:00:00Z",
        }
        with (
            patch("agents.mail_agent.get_access_token", return_value="tok"),
            patch(
                "requests.get",
                return_value=MagicMock(status_code=200, json=lambda: mock_data),
            ),
        ):
            result = agent.get_mail_body("mail999")
        assert result["body_text"] == ""


# --- mark_read ---


class TestMarkRead:
    def test_mark_read_patches_correct_url_and_payload(self, agent):
        with (
            patch("agents.mail_agent.get_access_token", return_value="tok"),
            patch("requests.patch", return_value=_ok(200)) as mock_patch,
        ):
            result = agent.mark_read("mail123", is_read=True)
        assert result is True
        url = mock_patch.call_args[0][0]
        assert "mail123" in url
        assert mock_patch.call_args[1]["json"] == {"isRead": True}

    def test_mark_unread_sends_false(self, agent):
        with (
            patch("agents.mail_agent.get_access_token", return_value="tok"),
            patch("requests.patch", return_value=_ok(200)) as mock_patch,
        ):
            result = agent.mark_read("mail123", is_read=False)
        assert result is True
        assert mock_patch.call_args[1]["json"] == {"isRead": False}

    def test_returns_false_on_error(self, agent):
        with (
            patch("agents.mail_agent.get_access_token", return_value="tok"),
            patch("requests.patch", return_value=_err(403)),
        ):
            result = agent.mark_read("mail123")
        assert result is False


# --- archive ---


class TestArchive:
    def test_posts_to_move_endpoint_with_archive_destination(self, agent):
        with (
            patch("agents.mail_agent.get_access_token", return_value="tok"),
            patch("requests.post", return_value=_ok(200)) as mock_post,
        ):
            result = agent.archive("mail456")
        assert result is True
        url = mock_post.call_args[0][0]
        body = mock_post.call_args[1]["json"]
        assert "mail456" in url
        assert url.endswith("/move")
        assert body == {"destinationId": "archive"}

    def test_returns_false_on_error(self, agent):
        with (
            patch("agents.mail_agent.get_access_token", return_value="tok"),
            patch("requests.post", return_value=_err(403)),
        ):
            result = agent.archive("mail456")
        assert result is False


# --- move ---


class TestMove:
    def test_posts_to_move_endpoint_with_destination(self, agent):
        with (
            patch("agents.mail_agent.get_access_token", return_value="tok"),
            patch("requests.post", return_value=_ok(200)) as mock_post,
        ):
            result = agent.move("mail789", "folder_abc")
        assert result is True
        url = mock_post.call_args[0][0]
        assert "mail789" in url
        assert url.endswith("/move")
        assert mock_post.call_args[1]["json"] == {"destinationId": "folder_abc"}

    def test_returns_false_on_error(self, agent):
        with (
            patch("agents.mail_agent.get_access_token", return_value="tok"),
            patch("requests.post", return_value=_err(404)),
        ):
            result = agent.move("mail789", "folder_abc")
        assert result is False


# --- delete ---


class TestDelete:
    def test_calls_delete_on_correct_url(self, agent):
        with (
            patch("agents.mail_agent.get_access_token", return_value="tok"),
            patch("requests.delete", return_value=_ok(204)) as mock_del,
        ):
            result = agent.delete("mail_xyz")
        assert result is True
        url = mock_del.call_args[0][0]
        assert "mail_xyz" in url

    def test_returns_false_on_error(self, agent):
        with (
            patch("agents.mail_agent.get_access_token", return_value="tok"),
            patch("requests.delete", return_value=_err(403)),
        ):
            result = agent.delete("mail_xyz")
        assert result is False


# --- reply ---


class TestReply:
    def test_posts_comment_to_reply_endpoint(self, agent):
        with (
            patch("agents.mail_agent.get_access_token", return_value="tok"),
            patch("requests.post", return_value=_ok(202)) as mock_post,
        ):
            result = agent.reply("mail_abc", "Danke, passt gut!")
        assert result is True
        url = mock_post.call_args[0][0]
        assert "mail_abc" in url
        assert url.endswith("/reply")
        assert mock_post.call_args[1]["json"] == {"comment": "Danke, passt gut!"}

    def test_returns_false_on_error(self, agent):
        with (
            patch("agents.mail_agent.get_access_token", return_value="tok"),
            patch("requests.post", return_value=_err(403)),
        ):
            result = agent.reply("mail_abc", "text")
        assert result is False


# --- forward ---


class TestForward:
    def test_sends_recipients_and_comment(self, agent):
        with (
            patch("agents.mail_agent.get_access_token", return_value="tok"),
            patch("requests.post", return_value=_ok(202)) as mock_post,
        ):
            result = agent.forward("mail_def", ["bob@example.com"], "Zur Info")
        assert result is True
        url = mock_post.call_args[0][0]
        assert "mail_def" in url
        assert url.endswith("/forward")
        payload = mock_post.call_args[1]["json"]
        assert (
            payload["toRecipients"][0]["emailAddress"]["address"] == "bob@example.com"
        )
        assert payload["comment"] == "Zur Info"

    def test_multiple_recipients(self, agent):
        with (
            patch("agents.mail_agent.get_access_token", return_value="tok"),
            patch("requests.post", return_value=_ok(202)) as mock_post,
        ):
            result = agent.forward("mail_def", ["a@x.com", "b@x.com"])
        assert result is True
        payload = mock_post.call_args[1]["json"]
        assert len(payload["toRecipients"]) == 2

    def test_empty_comment_is_allowed(self, agent):
        with (
            patch("agents.mail_agent.get_access_token", return_value="tok"),
            patch("requests.post", return_value=_ok(202)) as mock_post,
        ):
            result = agent.forward("mail_def", ["a@x.com"])
        assert result is True
        assert mock_post.call_args[1]["json"]["comment"] == ""

    def test_returns_false_on_error(self, agent):
        with (
            patch("agents.mail_agent.get_access_token", return_value="tok"),
            patch("requests.post", return_value=_err(403)),
        ):
            result = agent.forward("mail_def", ["b@x.com"])
        assert result is False
