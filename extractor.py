import re
from typing import Any
from urllib.parse import urlparse

TARGET_DOMAINS = ("mostaql.com", "khamsat.com", "nafezly.com")
URL_REGEX = re.compile(r"https?://[^\s<>\"]+|www\.[^\s<>\"]+", re.IGNORECASE)


def clean_url(url: str) -> str:
    """Strip trailing punctuation often caught at the end of URLs in chat messages."""
    return url.rstrip(".,;!?)>]\'\"")


def extract_urls_from_message(message: Any) -> list[str]:
    """
    Extracts all URLs from a Telethon Message, Aiogram Message, or raw string.
    Combines:
    1. Telegram entities (both Telethon and Aiogram formats).
    2. Regex scanning on text/raw_text/string.
    Preserves order and deduplicates.
    """
    found_urls: list[str] = []
    seen: set[str] = set()

    def add_url(raw: str | None):
        if not raw:
            return
        cleaned = clean_url(raw)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            found_urls.append(cleaned)

    # Case 1: Plain string input
    if isinstance(message, str):
        for match in URL_REGEX.findall(message):
            if not match.startswith("http"):
                match = f"https://{match}"
            add_url(match)
        return found_urls

    # Case 2: Telegram Message object (Telethon or Aiogram)
    text = (
        getattr(message, "raw_text", None)
        or getattr(message, "text", None)
        or getattr(message, "caption", None)
        or ""
    )

    # 1. Extract from Message Entities
    entities = getattr(message, "entities", None) or getattr(message, "caption_entities", None)
    if entities:
        for entity in entities:
            # Check for direct .url attribute (Aiogram or Telethon MessageEntityTextUrl)
            url_attr = getattr(entity, "url", None)
            if url_attr:
                add_url(url_attr)
            elif hasattr(entity, "offset") and hasattr(entity, "length") and text:
                offset = entity.offset
                length = entity.length
                slice_text = text[offset : offset + length]
                if "http" in slice_text or "www." in slice_text:
                    add_url(slice_text)

    # 2. Extract from raw text via regex (catches any missed plain URLs)
    for match in URL_REGEX.findall(text):
        if not match.startswith("http"):
            match = f"https://{match}"
        add_url(match)

    # 3. Extract from buttons and reply_markup (Telethon v1/v2 and Aiogram inline buttons)
    def _extract_from_btn(btn: Any):
        if not btn:
            return
        # Standard .url attribute
        u = getattr(btn, "url", None)
        if u:
            add_url(u)
            return
        # Telethon 2.x structure: btn.type.url (InlineButtonTypeUrl)
        b_type = getattr(btn, "type", None)
        if b_type:
            u2 = getattr(b_type, "url", None)
            if u2:
                add_url(u2)
                return
        # Button data or text containing URL
        data_attr = getattr(btn, "data", None)
        if isinstance(data_attr, (bytes, bytearray)):
            try:
                decoded = data_attr.decode("utf-8", errors="ignore")
                for m in URL_REGEX.findall(decoded):
                    add_url(m)
            except Exception:
                pass

    buttons = getattr(message, "buttons", None)
    if buttons:
        try:
            for row in buttons:
                if isinstance(row, (list, tuple)):
                    for btn in row:
                        _extract_from_btn(btn)
                else:
                    _extract_from_btn(row)
        except Exception:
            pass

    reply_markup = getattr(message, "reply_markup", None)
    if reply_markup:
        # Aiogram inline_keyboard
        inline_kb = getattr(reply_markup, "inline_keyboard", None)
        if inline_kb:
            try:
                for row in inline_kb:
                    for btn in row:
                        _extract_from_btn(btn)
            except Exception:
                pass
        # Telethon reply_markup rows
        rows = getattr(reply_markup, "rows", None)
        if rows:
            try:
                for row in rows:
                    for btn in getattr(row, "buttons", []):
                        _extract_from_btn(btn)
            except Exception:
                pass

    return found_urls


def filter_target_platform_urls(urls: list[str]) -> list[str]:
    """
    Filters and prioritizes URLs to those matching target freelance platforms:
    Mostaql, Khamsat, or Nafezly.
    Crucially prioritizes actual project/request URLs over user profile URLs!
    """
    matching: list[str] = []
    user_profiles: list[str] = []

    for url in urls:
        try:
            parsed = urlparse(url)
            hostname = (parsed.hostname or "").lower()
            path = (parsed.path or "").lower()

            if any(domain in hostname for domain in TARGET_DOMAINS):
                # Deprioritize user profile links (e.g., khamsat.com/user/xyz or mostaql.com/u/xyz)
                if "/user/" in path or path.startswith("/u/"):
                    user_profiles.append(url)
                else:
                    matching.append(url)
        except Exception:
            continue

    # Return request/project URLs first, profiles only as last resort
    return matching if matching else user_profiles
