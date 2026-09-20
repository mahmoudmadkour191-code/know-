from __future__ import annotations

import email
import imaplib
import os
import re
from email.header import decode_header
from typing import Any


class EmailAgent:
    """Read an owner-controlled IMAP mailbox. It does not create disposable accounts."""

    def __init__(self):
        self.host = os.getenv("MAIL_IMAP_HOST", "").strip()
        self.port = int(os.getenv("MAIL_IMAP_PORT", "993"))
        self.user = os.getenv("MAIL_IMAP_USER", "").strip()
        self.password = os.getenv("MAIL_IMAP_PASSWORD", "")
        self.mailbox = os.getenv("MAIL_IMAP_MAILBOX", "INBOX").strip() or "INBOX"

    @property
    def configured(self) -> bool:
        return bool(self.host and self.user and self.password)

    def _connect(self):
        if not self.configured:
            raise RuntimeError("Owner-controlled IMAP mailbox is not configured.")
        client = imaplib.IMAP4_SSL(self.host, self.port)
        client.login(self.user, self.password)
        client.select(self.mailbox)
        return client

    def latest_messages(self, limit: int = 10) -> list[dict[str, Any]]:
        client = self._connect()
        try:
            status, data = client.search(None, "ALL")
            if status != "OK":
                return []
            ids = data[0].split()[-min(max(limit, 1), 20):]
            out = []
            for msg_id in reversed(ids):
                status, parts = client.fetch(msg_id, "(RFC822)")
                if status != "OK" or not parts:
                    continue
                raw = next((item[1] for item in parts if isinstance(item, tuple) and len(item) > 1), None)
                if not raw:
                    continue
                msg = email.message_from_bytes(raw)
                subject = self._decode(msg.get("Subject", ""))
                sender = self._decode(msg.get("From", ""))
                body = self._body(msg)
                out.append({
                    "id": msg_id.decode(errors="ignore"),
                    "from": sender[:300],
                    "subject": subject[:300],
                    "body": body[:4000],
                })
            return out
        finally:
            try:
                client.logout()
            except Exception:
                pass

    def find_verification_code(self, hint: str = "") -> dict[str, Any]:
        messages = self.latest_messages(15)
        lowered_hint = hint.lower().strip()
        for message in messages:
            hay = (message["subject"] + " " + message["body"]).lower()
            if lowered_hint and lowered_hint not in hay:
                continue
            for pattern in (r"\b(\d{4,8})\b", r"\b([A-Z0-9]{6,10})\b"):
                match = re.search(pattern, hay, re.I)
                if match:
                    return {"ok": True, "code": match.group(1), "message": message}
        return {"ok": False, "error": "No likely verification code found."}

    @staticmethod
    def _decode(value: str) -> str:
        result = []
        for chunk, encoding in decode_header(value or ""):
            if isinstance(chunk, bytes):
                result.append(chunk.decode(encoding or "utf-8", errors="replace"))
            else:
                result.append(chunk)
        return "".join(result)

    @staticmethod
    def _body(msg) -> str:
        if msg.is_multipart():
            chunks = []
            for part in msg.walk():
                if part.get_content_type() == "text/plain" and part.get_content_disposition() != "attachment":
                    payload = part.get_payload(decode=True)
                    if payload:
                        chunks.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
            return "\n".join(chunks)
        payload = msg.get_payload(decode=True)
        return payload.decode(msg.get_content_charset() or "utf-8", errors="replace") if payload else ""
