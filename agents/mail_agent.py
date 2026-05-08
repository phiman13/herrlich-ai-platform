import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import anthropic
import requests

try:
    from microsoft_auth import get_access_token
except ImportError:
    from agents.microsoft_auth import get_access_token

logger = logging.getLogger("jarvis.mail")

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


@dataclass
class Mail:
    id: str
    subject: str
    sender_name: str
    sender_email: str
    received: datetime
    is_read: bool
    preview: str
    folder: str
    has_attachments: bool


@dataclass
class MailFolder:
    id: str
    name: str
    parent_id: Optional[str]
    child_count: int
    unread_count: int
    total_count: int


class MailAgent:
    def __init__(self):
        self.logger = logging.getLogger("jarvis.mail")

    def _get_headers(self) -> dict:
        token = get_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def _get(self, path: str, params: dict = None) -> dict:
        url = f"{GRAPH_BASE}{path}"
        r = requests.get(url, headers=self._get_headers(), params=params, timeout=15)
        if r.status_code != 200:
            self.logger.error(f"Graph API error: {r.status_code} {r.text[:500]}")
            r.raise_for_status()
        return r.json()

    def _parse_mail(self, item: dict, folder_name: str = "") -> Mail:
        sender = item.get("from", {}).get("emailAddress", {})
        return Mail(
            id=item["id"],
            subject=item.get("subject") or "(kein Betreff)",
            sender_name=sender.get("name", ""),
            sender_email=sender.get("address", ""),
            received=datetime.fromisoformat(
                item["receivedDateTime"].replace("Z", "+00:00")
            ),
            is_read=item.get("isRead", False),
            preview=(item.get("bodyPreview") or "")[:200],
            folder=folder_name,
            has_attachments=item.get("hasAttachments", False),
        )

    def _parse_folder(self, f: dict) -> MailFolder:
        return MailFolder(
            id=f["id"],
            name=f["displayName"],
            parent_id=f.get("parentFolderId"),
            child_count=f.get("childFolderCount", 0),
            unread_count=f.get("unreadItemCount", 0),
            total_count=f.get("totalItemCount", 0),
        )

    def list_folders(self) -> list:
        folders = []
        data = self._get("/me/mailFolders", params={"$top": 100})
        for f in data.get("value", []):
            folders.append(self._parse_folder(f))
            if f.get("childFolderCount", 0) > 0:
                folders.extend(self._get_child_folders(f["id"]))
        return folders

    def _get_child_folders(self, parent_id: str) -> list:
        result = []
        data = self._get(
            f"/me/mailFolders/{parent_id}/childFolders",
            params={"$top": 100},
        )
        for f in data.get("value", []):
            result.append(self._parse_folder(f))
            if f.get("childFolderCount", 0) > 0:
                result.extend(self._get_child_folders(f["id"]))
        return result

    def find_folder_by_name(self, name: str) -> Optional[MailFolder]:
        folders = self.list_folders()
        name_lower = name.lower()
        for f in folders:
            if f.name.lower() == name_lower:
                return f
        for f in folders:
            if name_lower in f.name.lower():
                return f
        return None

    def quick_scan(self, n: int = 10, folder_id: str = None) -> list:
        path = f"/me/mailFolders/{folder_id}/messages" if folder_id else "/me/messages"
        params = {
            "$top": n,
            "$orderby": "receivedDateTime desc",
            "$select": "id,subject,from,receivedDateTime,isRead,bodyPreview,hasAttachments",
        }
        data = self._get(path, params=params)
        folder_name = ""
        if folder_id:
            try:
                folder_name = self._get(
                    f"/me/mailFolders/{folder_id}",
                    params={"$select": "displayName"},
                ).get("displayName", "")
            except Exception:
                pass
        return [self._parse_mail(m, folder_name) for m in data.get("value", [])]

    def get_unread(self, n: int = 20, folder_id: str = None) -> list:
        path = f"/me/mailFolders/{folder_id}/messages" if folder_id else "/me/messages"
        params = {
            "$top": n,
            "$orderby": "receivedDateTime desc",
            "$filter": "isRead eq false",
            "$select": "id,subject,from,receivedDateTime,isRead,bodyPreview,hasAttachments",
        }
        data = self._get(path, params=params)
        return [self._parse_mail(m) for m in data.get("value", [])]

    def get_inbox_unread(self, n: int = 30) -> list:
        """Fetch unread messages from Inbox only (naturally excludes Newsletter/Job subfolders)."""
        params = {
            "$top": n,
            "$orderby": "receivedDateTime desc",
            "$filter": "isRead eq false",
            "$select": "id,subject,from,receivedDateTime,isRead,bodyPreview,hasAttachments",
        }
        data = self._get("/me/mailFolders/inbox/messages", params=params)
        return [self._parse_mail(m, "inbox") for m in data.get("value", [])]

    def search(
        self,
        sender: str = None,
        subject_contains: str = None,
        since: datetime = None,
        folder_id: str = None,
        n: int = 25,
    ) -> list:
        path = f"/me/mailFolders/{folder_id}/messages" if folder_id else "/me/messages"

        if sender and "@" in sender and not subject_contains and not since:
            esc = sender.replace("'", "''")
            params = {
                "$top": n,
                "$orderby": "receivedDateTime desc",
                "$filter": f"from/emailAddress/address eq '{esc}'",
                "$select": "id,subject,from,receivedDateTime,isRead,bodyPreview,hasAttachments",
            }
            headers = self._get_headers()
        else:
            search_parts = []
            if sender:
                search_parts.append(sender)
            if subject_contains:
                search_parts.append(subject_contains)

            if not search_parts:
                return []

            search_string = " ".join(search_parts)
            params = {
                "$top": n,
                "$search": f'"{search_string}"',
                "$select": "id,subject,from,receivedDateTime,isRead,bodyPreview,hasAttachments",
            }
            headers = self._get_headers()
            headers["ConsistencyLevel"] = "eventual"

        url = f"{GRAPH_BASE}{path}"
        r = requests.get(url, headers=headers, params=params, timeout=15)
        if r.status_code != 200:
            self.logger.error(f"Graph search error: {r.status_code} {r.text[:500]}")
            r.raise_for_status()
        data = r.json()
        mails = [self._parse_mail(m) for m in data.get("value", [])]

        if since:
            mails = [m for m in mails if m.received >= since]

        return mails

    def send_mail(self, to_email: str, subject: str, body: str) -> bool:
        """Send mail via MS Graph POST /me/sendMail. Returns True on success."""
        payload = {
            "message": {
                "subject": subject,
                "body": {"contentType": "Text", "content": body},
                "toRecipients": [{"emailAddress": {"address": to_email}}],
            },
            "saveToSentItems": True,
        }
        try:
            r = requests.post(
                f"{GRAPH_BASE}/me/sendMail",
                headers=self._get_headers(),
                json=payload,
                timeout=15,
            )
            r.raise_for_status()
            self.logger.info("Mail gesendet an %s", to_email)
            return True
        except Exception as e:
            self.logger.error("send_mail fehlgeschlagen: %s", e)
            return False

    def _patch(self, path: str, json_data: dict) -> None:
        url = f"{GRAPH_BASE}{path}"
        r = requests.patch(url, headers=self._get_headers(), json=json_data, timeout=15)
        if r.status_code not in (200, 204):
            self.logger.error("Graph PATCH error: %s %s", r.status_code, r.text[:200])
            r.raise_for_status()

    def _post_action(self, path: str, json_data: dict | None = None) -> None:
        url = f"{GRAPH_BASE}{path}"
        r = requests.post(
            url, headers=self._get_headers(), json=json_data or {}, timeout=15
        )
        if r.status_code not in (200, 202, 204):
            self.logger.error("Graph POST error: %s %s", r.status_code, r.text[:200])
            r.raise_for_status()

    def _delete_req(self, path: str) -> None:
        url = f"{GRAPH_BASE}{path}"
        r = requests.delete(url, headers=self._get_headers(), timeout=15)
        if r.status_code not in (200, 204):
            self.logger.error("Graph DELETE error: %s %s", r.status_code, r.text[:200])
            r.raise_for_status()

    def get_mail_body(self, mail_id: str) -> dict:
        import re as _re

        data = self._get(
            f"/me/messages/{mail_id}",
            params={"$select": "id,subject,from,receivedDateTime,body"},
        )
        body_content = data.get("body", {}).get("content", "")
        body_text = _re.sub(r"<[^>]+>", " ", body_content)
        body_text = _re.sub(r"\s+", " ", body_text).strip()[:500]
        sender = data.get("from", {}).get("emailAddress", {})
        return {
            "id": data["id"],
            "subject": data.get("subject", "(kein Betreff)"),
            "sender_name": sender.get("name", ""),
            "sender_email": sender.get("address", ""),
            "received": data.get("receivedDateTime", ""),
            "body_text": body_text,
        }

    def mark_read(self, mail_id: str, is_read: bool = True) -> bool:
        try:
            self._patch(f"/me/messages/{mail_id}", {"isRead": is_read})
            return True
        except Exception as e:
            self.logger.error("mark_read fehlgeschlagen: %s", e)
            return False

    def get_recent_mails(self, n: int = 150, since: datetime | None = None) -> list:
        params = {
            "$top": n,
            "$orderby": "receivedDateTime desc",
            "$select": "id,subject,from,receivedDateTime,isRead,bodyPreview,hasAttachments",
        }
        data = self._get("/me/mailFolders/inbox/messages", params=params)
        mails = [self._parse_mail(m, "inbox") for m in data.get("value", [])]
        if since:
            mails = [m for m in mails if m.received >= since]
        return mails

    def smart_search(
        self,
        query: str,
        n: int = 150,
        since: datetime | None = None,
    ) -> list:
        mails = self.get_recent_mails(n=n, since=since)
        if not mails:
            return []

        from zoneinfo import ZoneInfo

        berlin = ZoneInfo("Europe/Berlin")
        lines = []
        for i, m in enumerate(mails):
            sender = (m.sender_name or m.sender_email or "?")[:40]
            date_str = m.received.astimezone(berlin).strftime("%d.%m %H:%M")
            lines.append(
                f"{i}: [{date_str}] {sender} | {m.subject[:80]} | {m.preview[:100]}"
            )

        client = anthropic.Anthropic()
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            temperature=0,
            system=(
                "Du analysierst eine E-Mail-Liste. Gib die Indizes (kommagetrennt) der Mails zurück, "
                "die zur Suchanfrage passen. Antworte NUR mit Zahlen kommagetrennt, z.B.: 3,7,12 "
                "— oder 'none' falls keine passen."
            ),
            messages=[
                {
                    "role": "user",
                    "content": f"Suchanfrage: {query}\n\nMails:\n" + "\n".join(lines),
                }
            ],
        )
        result = resp.content[0].text.strip()
        if result.lower() == "none":
            return []

        indices = [int(x.strip()) for x in result.split(",") if x.strip().isdigit()]
        return [mails[i] for i in indices if i < len(mails)]
