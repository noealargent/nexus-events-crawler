"""Stable shard of a site by its website host, so one host is only ever read by one
matrix job (the per-host delay in import_events.py then holds across the whole run)."""
from __future__ import annotations

import hashlib
from urllib.parse import urlparse


def site_host(website: str) -> str:
    value = (website or "").strip()
    if "//" not in value:
        value = "https://" + value
    host = urlparse(value).netloc.lower().split(":")[0]
    host = host.removeprefix("www.").removeprefix("m.")
    return host


def shard_of(website: str, shards: int) -> int:
    if shards <= 1:
        return 0
    digest = hashlib.sha1(site_host(website).encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % shards
