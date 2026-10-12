"""Cineville accounts stored in the config entry.

entry.data[CONF_ACCOUNTS] is a list of {user_id, account_name, tokens}. Several people can be logged in;
their watchlists are combined on the card. These helpers return new data dicts (entries are immutable).
"""

from __future__ import annotations

from typing import Any

from .const import CONF_ACCOUNT_NAME, CONF_ACCOUNTS, CONF_TOKENS, CONF_USER_ID

# Version 1 stored a single account directly in entry.data under these keys
_V1_KEYS = (CONF_TOKENS, CONF_USER_ID, CONF_ACCOUNT_NAME)


def accounts(data: dict[str, Any]) -> list[dict[str, Any]]:
    return list(data.get(CONF_ACCOUNTS) or [])


def find(data: dict[str, Any], user_id: str) -> dict[str, Any] | None:
    return next((a for a in accounts(data) if a[CONF_USER_ID] == user_id), None)


def upsert(data: dict[str, Any], account: dict[str, Any]) -> dict[str, Any]:
    """Add an account, or replace it if the same Cineville user logs in again."""
    others = [a for a in accounts(data) if a[CONF_USER_ID] != account[CONF_USER_ID]]
    return {**data, CONF_ACCOUNTS: [*others, account]}


def remove(data: dict[str, Any], user_ids: list[str]) -> dict[str, Any]:
    return {**data, CONF_ACCOUNTS: [a for a in accounts(data) if a[CONF_USER_ID] not in user_ids]}


def with_tokens(data: dict[str, Any], user_id: str, tokens: dict[str, Any]) -> dict[str, Any]:
    return {
        **data,
        CONF_ACCOUNTS: [{**a, CONF_TOKENS: tokens} if a[CONF_USER_ID] == user_id else a for a in accounts(data)],
    }


def migrate_v1(data: dict[str, Any]) -> dict[str, Any]:
    """v1 (one account in entry.data) -> v2 (list of accounts)."""
    new = {k: v for k, v in data.items() if k not in _V1_KEYS}
    new[CONF_ACCOUNTS] = []
    if data.get(CONF_TOKENS) and data.get(CONF_USER_ID):
        new[CONF_ACCOUNTS].append({
            CONF_USER_ID: data[CONF_USER_ID],
            CONF_ACCOUNT_NAME: data.get(CONF_ACCOUNT_NAME) or "",
            CONF_TOKENS: data[CONF_TOKENS],
        })
    return new


def display_name(info: dict[str, Any]) -> str:
    """Short name for markers on the card: first name, else full name, else the email's local part."""
    return (info.get("given_name") or info.get("name") or (info.get("email") or "").split("@")[0] or "?").strip()
