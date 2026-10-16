"""Telegram Bot API delivery. Splits long reports at the 4096-char limit.

The function returns the message ids Telegram acknowledged; the caller only
reports "delivered" when that list is non-empty.
"""

from __future__ import annotations

import httpx

from ..providers.base import make_client

API = "https://api.telegram.org/bot{token}/{method}"
LIMIT = 4000  # leave headroom under 4096


def _chunks(text: str) -> list[str]:
    out, cur = [], ""
    for para in text.split("\n\n"):
        cand = f"{cur}\n\n{para}" if cur else para
        if len(cand) <= LIMIT:
            cur = cand
        else:
            if cur:
                out.append(cur)
            cur = para[:LIMIT]
    if cur:
        out.append(cur)
    return out


def send_html(token: str, chat_id: str, html: str, *, client: httpx.Client | None = None) -> list[int]:
    own = client is None
    client = client or make_client()
    ids: list[int] = []
    try:
        for part in _chunks(html):
            r = client.post(
                API.format(token=token, method="sendMessage"),
                json={"chat_id": chat_id, "text": part, "parse_mode": "HTML", "disable_web_page_preview": True},
            )
            body = r.json()
            if not body.get("ok"):
                raise RuntimeError(f"Telegram error: {body.get('description', body)}")
            ids.append(body["result"]["message_id"])
        return ids
    finally:
        if own:
            client.close()


def check_bot(token: str, *, client: httpx.Client | None = None) -> str:
    own = client is None
    client = client or make_client()
    try:
        body = client.get(API.format(token=token, method="getMe")).json()
        if not body.get("ok"):
            raise RuntimeError(f"Telegram getMe failed: {body}")
        return body["result"]["username"]
    finally:
        if own:
            client.close()
