"""
Newsletter ingester via Gmail IMAP.
Polls a dedicated Gmail inbox for company newsletters,
extracts content, and stores as content_items.

Setup:
1. Create a Gmail account (e.g. forge.newsletters@gmail.com)
2. Enable IMAP in Gmail settings
3. Enable 2FA, then create an App Password at myaccount.google.com/apppasswords
4. Set NEWSLETTER_EMAIL, NEWSLETTER_APP_PASSWORD, NEWSLETTER_IMAP_HOST in .env
5. Subscribe to company newsletters with this email
"""
import os
import uuid
import email
import hashlib
import imaplib
from datetime import datetime
from email.header import decode_header
from typing import Optional

from bs4 import BeautifulSoup

from src.db.database import get_db


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _get_config() -> dict:
    return {
        "email": os.getenv("NEWSLETTER_EMAIL", ""),
        "password": os.getenv("NEWSLETTER_APP_PASSWORD", ""),
        "imap_host": os.getenv("NEWSLETTER_IMAP_HOST", "imap.gmail.com"),
        "imap_port": int(os.getenv("NEWSLETTER_IMAP_PORT", "993")),
    }


def is_configured() -> bool:
    cfg = _get_config()
    return bool(cfg["email"] and cfg["password"])


def _hash(source: str, title: str) -> str:
    raw = f"{source.strip().lower()}|{title.strip().lower()}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Email helpers
# ---------------------------------------------------------------------------

def _decode_header_value(value: str) -> str:
    """Decode MIME-encoded header into plain text."""
    if not value:
        return ""
    parts = decode_header(value)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return " ".join(decoded)


def _extract_text_from_html(html: str) -> str:
    """Strip HTML tags and extract readable text."""
    soup = BeautifulSoup(html, "lxml")
    # Remove script/style
    for tag in soup(["script", "style", "head"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    # Collapse multiple newlines
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def _extract_body(msg: email.message.Message) -> str:
    """Extract the best available text body from an email."""
    text_body = ""
    html_body = ""

    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))
            if "attachment" in disposition:
                continue
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            charset = part.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            if ct == "text/plain":
                text_body = text
            elif ct == "text/html":
                html_body = text
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                html_body = text
            else:
                text_body = text

    # Prefer HTML (more structured), fall back to plain text
    if html_body:
        return _extract_text_from_html(html_body)
    return text_body


def _match_to_startup(sender: str, subject: str, body: str) -> Optional[dict]:
    """Try to match an email to a known startup."""
    db = get_db()
    startups = [dict(row) for row in db.execute("SELECT * FROM startups").fetchall()]
    check_text = f"{sender} {subject} {body}".lower()

    for startup in startups:
        name = startup["name"].lower()
        if name in check_text:
            return startup
        if startup.get("legal_name"):
            if startup["legal_name"].lower() in check_text:
                return startup
        if startup.get("contact_email"):
            if startup["contact_email"].lower() in sender.lower():
                return startup
    return None


# ---------------------------------------------------------------------------
# IMAP ingestion
# ---------------------------------------------------------------------------

PROCESSED_LABEL = "Ingested"


def ingest_newsletters(max_emails: int = 50) -> dict:
    """
    Connect to Gmail via IMAP, read unprocessed emails,
    extract content, match to startups, and store.
    Returns ingestion stats.

    This is synchronous (IMAP library is blocking).
    """
    stats = {"found": 0, "new": 0, "duplicate": 0, "matched": 0, "errors": 0}

    cfg = _get_config()
    if not is_configured():
        return {**stats, "status": "not_configured"}

    try:
        # Connect
        mail = imaplib.IMAP4_SSL(cfg["imap_host"], cfg["imap_port"])
        mail.login(cfg["email"], cfg["password"])
        mail.select("INBOX")

        # Search for unseen emails
        status, data = mail.search(None, "UNSEEN")
        if status != "OK" or not data[0]:
            mail.logout()
            return {**stats, "status": "no_new_emails"}

        email_ids = data[0].split()[:max_emails]
        stats["found"] = len(email_ids)

        db = get_db()

        for eid in email_ids:
            try:
                status, msg_data = mail.fetch(eid, "(RFC822)")
                if status != "OK":
                    stats["errors"] += 1
                    continue

                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)

                subject = _decode_header_value(msg.get("Subject", ""))
                sender = _decode_header_value(msg.get("From", ""))
                date_str = msg.get("Date", datetime.utcnow().isoformat())
                message_id = msg.get("Message-ID", "")

                body = _extract_body(msg)
                if not body or len(body) < 20:
                    continue

                title = subject or (body[:100] + "..." if len(body) > 100 else body)

                # De-dup
                content_hash = _hash(message_id or f"{sender}:{subject}", title)
                existing = db.execute(
                    "SELECT id FROM content_items WHERE content_hash = ?",
                    (content_hash,)
                ).fetchone()

                if existing:
                    stats["duplicate"] += 1
                    continue

                # Match to startup
                matched = _match_to_startup(sender, subject, body)
                if matched:
                    stats["matched"] += 1

                item_id = str(uuid.uuid4())
                db.execute(
                    """INSERT INTO content_items
                    (id, startup_id, source_type, source_name, url, title,
                     published_at, raw_content, content_hash, classification)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (item_id, matched["id"] if matched else None,
                     "newsletter", f"Email: {sender[:60]}",
                     "", title, date_str, body, content_hash, "unclassified")
                )
                stats["new"] += 1

                # Mark as seen (it already is via IMAP fetch)
                mail.store(eid, "+FLAGS", "\\Seen")

            except Exception as e:
                print(f"  [Newsletter] Error processing email: {e}")
                stats["errors"] += 1

        db.commit()
        mail.logout()

    except imaplib.IMAP4.error as e:
        print(f"  [Newsletter] IMAP error: {e}")
        return {**stats, "status": "imap_error", "error": str(e)}
    except Exception as e:
        print(f"  [Newsletter] Connection error: {e}")
        return {**stats, "status": "connection_error", "error": str(e)}

    return {**stats, "status": "completed"}


def check_connection() -> dict:
    """Verify IMAP connection is working."""
    if not is_configured():
        return {
            "status": "not_configured",
            "message": "Set NEWSLETTER_EMAIL and NEWSLETTER_APP_PASSWORD in .env"
        }

    cfg = _get_config()
    try:
        mail = imaplib.IMAP4_SSL(cfg["imap_host"], cfg["imap_port"])
        mail.login(cfg["email"], cfg["password"])
        mail.select("INBOX")
        status, data = mail.search(None, "ALL")
        count = len(data[0].split()) if data[0] else 0
        mail.logout()
        return {
            "status": "connected",
            "inbox_count": count,
            "email": cfg["email"],
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
