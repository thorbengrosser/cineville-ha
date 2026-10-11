#!/usr/bin/env python3
"""Check that the Cineville API still behaves the way docs/api describes.

Stdlib only. Usage:  python3 docs/api/smoke_test.py
Exit code 0 = all checks passed, 1 = something changed (see FAIL lines).
"""
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = "https://api.cineville.de"
STUDIO_KINO = "88beb28b-cec3-43f8-b1f2-eeb7d58c1a6b"
KNOWN_TAGS = {"3d", "70mm", "classic", "modernClassic", "special", "englishSubs", "preview", "sneakPreview"}

failures = 0


def request(method, path, body=None):
    headers = {"Accept": "application/json", "User-Agent": "cineville-ha-smoke-test"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as err:
        try:
            return err.code, json.loads(err.read())
        except ValueError:
            return err.code, None


def check(name, ok, detail=""):
    global failures
    print(f"{'ok  ' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    if not ok:
        failures += 1


def main():
    now = datetime.now(timezone.utc)
    window = {
        "gte": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "lt": (now + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    }
    base_query = {
        "productionId": {"isNull": False},
        "isHidden": {"eq": False},
        "startDate": window,
        "venue": {"collection": {"cities": {"in": ["hamburg"]}}},
        "embed": {"production": True, "venue": True},
        "sort": {"startDate": "asc"},
    }

    # 1. Main search endpoint + embedded shape
    status, data = request("POST", "/events/search", {**base_query, "page": {"limit": 5}})
    check("POST /events/search returns 200", status == 200, f"HTTP {status}")
    events = (data or {}).get("_embedded", {}).get("events", [])
    check("Hamburg has events in the next 7 days", len(events) > 0, f"totalCount={data and data.get('totalCount')}")
    if events:
        ev = events[0]
        prod = ev.get("_embedded", {}).get("production") or {}
        venue = ev.get("_embedded", {}).get("venue") or {}
        check("event has startDate/venueId/attributes", all(k in ev for k in ("startDate", "venueId", "attributes")))
        check("embedded production has title + assets", "title" in prod and "assets" in prod)
        check("embedded production has localizableAttributes.shortDescription",
              "shortDescription" in prod.get("localizableAttributes", {}))
        check("embedded venue has name + address", "name" in venue and "address" in venue)
        starts = [e["startDate"] for e in events]
        check("sort startDate asc is honoured", starts == sorted(starts))
    total = (data or {}).get("totalCount", 0)

    # 2. Pagination: re-POST the same body to _links.next.href
    status, page1 = request("POST", "/events/search", {**base_query, "page": {"limit": 2}})
    nxt = (page1 or {}).get("_links", {}).get("next", {}).get("href")
    check("pagination returns a next link", bool(nxt) or total <= 2)
    if nxt:
        status, page2 = request("POST", nxt, {**base_query, "page": {"limit": 2}})
        ids1 = {e["id"] for e in page1["_embedded"]["events"]}
        ids2 = {e["id"] for e in (page2 or {}).get("_embedded", {}).get("events", [])}
        check("next page returns different events", status == 200 and ids2 and not (ids1 & ids2))

    # 3. Filters documented as working
    status, data = request("POST", "/events/search",
                           {**base_query, "venueId": {"in": [STUDIO_KINO]}, "page": {"limit": 1}})
    narrowed = (data or {}).get("totalCount")
    check("venueId.in narrows results", status == 200 and narrowed is not None and narrowed < total,
          f"{narrowed} < {total}")

    # 4. Documented quirks
    status, data = request("POST", "/events/search", {**base_query, "bogusField": {"eq": 1}, "page": {"limit": 1}})
    check("unknown filter keys are still silently ignored", status == 200 and data.get("totalCount") == total,
          "if this fails the API got stricter, which is good, but update querying.md")
    status, _ = request("POST", "/events/search", {"page": {"limit": 1001}})
    check("page.limit > 1000 is rejected", status == 400, f"HTTP {status}")

    # 5. Reference data
    status, data = request("GET", f"/venues/{STUDIO_KINO}")
    check("known venue ID still resolves", status == 200 and data.get("name") == "Studio Kino",
          f"HTTP {status}, name={data and data.get('name')}")
    status, data = request("GET", "/production-types/film")
    tags = set(
        (data or {}).get("eventAttributesSchema", {}).get("properties", {})
        .get("tags", {}).get("items", {}).get("enum", [])
    )
    check("event tag enum unchanged", tags == KNOWN_TAGS, f"now: {sorted(tags)}")

    # 6. The old GraphQL endpoint (informational)
    try:
        req = urllib.request.Request("https://cineville.de/api/graphql", data=b"{}", method="POST",
                                     headers={"Content-Type": "application/json"})
        code = urllib.request.urlopen(req, timeout=15).status
    except urllib.error.HTTPError as err:
        code = err.code
    print(f"info  old GraphQL endpoint answers HTTP {code} (405 expected since 2026)")

    print()
    print("All checks passed." if failures == 0 else f"{failures} check(s) failed. The API may have changed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
