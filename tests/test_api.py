import time
from datetime import datetime, timezone

import pytest

from conftest import make_event
from custom_components.cineville.api import CinevilleClient
from custom_components.cineville.auth import CinevilleAuth, Tokens
from custom_components.cineville.exceptions import (
    CinevilleAuthError,
    CinevilleConnectionError,
    CinevilleError,
)

START = datetime(2026, 10, 11, 2, 0, tzinfo=timezone.utc)
END = datetime(2026, 10, 12, 2, 0, tzinfo=timezone.utc)
STUDIO = "88beb28b-cec3-43f8-b1f2-eeb7d58c1a6b"


def client(session, fake_api, **kwargs):
    return CinevilleClient(session, api_url=fake_api.url, website_url=fake_api.url, **kwargs)


def logged_in(session, fake_api):
    return CinevilleAuth(session, Tokens("access-1", "refresh-1", time.time() + 3600), api_url=fake_api.url)


def page(events, next_href=None):
    links = {"self": {"href": "/events/search?page[limit]=1000"}}
    if next_href:
        links["next"] = {"href": next_href}
    return {"count": len(events), "totalCount": 99, "_links": links, "_embedded": {"events": events}}


async def test_get_showtimes_follows_pagination_and_sorts(session, fake_api, event):
    late = make_event(event, "e-late", "2026-10-11T20:30:00.000Z")
    early = make_event(event, "e-early", "2026-10-11T15:00:00.000Z")
    unmatched = make_event(event, "e-raw", "2026-10-11T16:00:00.000Z", productionId=None)
    del unmatched["_embedded"]["production"]
    fake_api.add("POST", "/events/search", page([late, unmatched], "/events/search?page[limit]=1000&page[after]=abc"))
    fake_api.add("POST", "/events/search", page([early]))

    result = await client(session, fake_api).get_showtimes(START, END, venue_ids=[STUDIO])

    assert [s.id for s in result] == ["e-early", "e-late"]
    sent = fake_api.sent("POST", "/events/search")
    assert len(sent) == 2
    assert sent[1].query == {"page[limit]": "1000", "page[after]": "abc"}  # cursor from the next href
    assert sent[0].json == sent[1].json  # the same filter body is re-POSTed
    body = sent[0].json
    assert body["venueId"] == {"in": [STUDIO]}
    assert "venue" not in body
    assert body["productionId"] == {"isNull": False}
    assert body["startDate"] == {"gte": "2026-10-11T02:00:00.000Z", "lt": "2026-10-12T02:00:00.000Z"}
    assert body["embed"] == {"production": True, "venue": True}
    assert sent[0].headers["locale"] == "de-DE"


async def test_get_showtimes_by_city(session, fake_api):
    fake_api.add("POST", "/events/search", page([]))
    await client(session, fake_api).get_showtimes(START, END, city_id="hamburg")
    assert fake_api.sent("POST", "/events/search")[0].json["venue"] == {"collection": {"cities": {"in": ["hamburg"]}}}


async def test_get_showtimes_needs_a_filter(session, fake_api):
    with pytest.raises(ValueError):
        await client(session, fake_api).get_showtimes(START, END)


async def test_server_error_is_a_connection_error(session, fake_api):
    fake_api.add("POST", "/events/search", status=503, body="unavailable")
    with pytest.raises(CinevilleConnectionError):
        await client(session, fake_api).get_showtimes(START, END, city_id="hamburg")


async def test_unreachable_server_is_a_connection_error(session):
    c = CinevilleClient(session, api_url="http://127.0.0.1:9")  # nothing listens on the discard port
    with pytest.raises(CinevilleConnectionError):
        await c.get_showtimes(START, END, city_id="hamburg")


async def test_client_error_is_reported(session, fake_api):
    fake_api.add("POST", "/events/search", {"statusCode": 400, "message": "Validation failed"}, status=400)
    with pytest.raises(CinevilleError, match="HTTP 400"):
        await client(session, fake_api).get_showtimes(START, END, city_id="hamburg")


def venue(vid, name, city):
    return {"id": vid, "name": name, "slug": vid, "address": {"city": city}}


async def test_get_cities_drops_empty_and_duplicate_collections(session, fake_api):
    fake_api.add("GET", "/collections", {"_links": {"self": {"href": "/collections"}}, "_embedded": {"collections": [
        {"id": "hamburg"}, {"id": "k"}, {"id": "nuernberg"}, {"id": "Nürnberg"},
    ]}})
    by_city = {
        "hamburg": [venue("a", "Abaton", "Hamburg"), venue("b", "B-Movie", "Hamburg")],
        "k": [],
        "nuernberg": [venue("c", "Casablanca", "Nürnberg"), venue("d", "Meisengeige", "Nürnberg")],
        "Nürnberg": [venue("c", "Casablanca", "Nürnberg")],
    }

    def venues_for(req):
        assert req.query["isHidden[eq]"] == "false"
        city = req.query["collection[cities][in][0]"]
        return 200, {"_links": {"self": {"href": "/venues"}}, "_embedded": {"venues": by_city[city]}}

    fake_api.add("GET", "/venues", handler=venues_for)

    cities = await client(session, fake_api).get_cities()
    assert [(c.id, c.name, c.venue_count) for c in cities] == [("hamburg", "Hamburg", 2), ("nuernberg", "Nürnberg", 2)]
    assert fake_api.sent("GET", "/collections")[0].query["collectionGroupId[eq]"] == "cities"


async def test_get_tenant_reads_website_config(session, fake_api):
    fake_api.add("GET", "/api/tenants", [
        {"id": "cineville.nl", "cultureKitApiUrl": "https://api.cineville.nl"},
        {"id": "cineville.de", "cultureKitApiUrl": "https://api.cineville.de", "appAuthClientId": "app",
         "scheduleWeek": {"startHour": 4}},
    ])
    tenant = await client(session, fake_api).get_tenant()
    assert tenant.id == "cineville.de"
    assert tenant.app_auth_client_id == "app"


async def test_member_endpoints_send_bearer_token(session, fake_api):
    fake_api.add("GET", "/users/u1/watchlist/production-ids", {"productionIds": ["p1", "p2"]})
    ids = await client(session, fake_api, auth=logged_in(session, fake_api)).get_watchlist_ids("u1")
    assert ids == {"p1", "p2"}
    assert fake_api.requests[0].headers["Authorization"] == "Bearer access-1"


async def test_seen_ids(session, fake_api):
    fake_api.add("GET", "/users/u1/visit-history/production-ids", {"productionIds": ["p3"]})
    assert await client(session, fake_api, auth=logged_in(session, fake_api)).get_seen_ids("u1") == {"p3"}


async def test_member_endpoint_without_login_fails(session, fake_api):
    with pytest.raises(CinevilleAuthError):
        await client(session, fake_api).get_seen_ids("u1")


async def test_unauthorized_response_is_auth_error(session, fake_api):
    fake_api.add("GET", "/connect/userinfo", {"message": "Unauthorized", "statusCode": 401}, status=401)
    with pytest.raises(CinevilleAuthError):
        await client(session, fake_api, auth=logged_in(session, fake_api)).get_user_id()
