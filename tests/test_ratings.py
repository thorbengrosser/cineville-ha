"""Ratings: TMDB matching, OMDb parsing, the cache manager and the options step."""

import time
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util

from custom_components.cineville.const import CONF_OMDB_KEY, CONF_TMDB_KEY, DOMAIN, SERVICE_GET_PROGRAM
from custom_components.cineville.models import Film
from custom_components.cineville.ratings import Rating, RatingsAuthError, RatingsClient, RatingsError, norm
from custom_components.cineville.ratings_manager import RatingsManager
from ha_helpers import CLIENT, NOW, PRIMETIME, mock_entry, showtimes

RATINGS = "custom_components.cineville.ratings.RatingsClient"


def test_norm():
    assert norm("Hope (2026)") == "hope"
    assert norm("Paweł Pawlikowski") == "pawel pawlikowski"
    assert norm("Almanya – Willkommen in Deutschland") == "almanya willkommen in deutschland"
    assert norm("Søren Kragh-Jacobsen") == "soren kragh jacobsen"


@pytest.mark.parametrize(
    ("rating", "shown"),
    [(Rating(1, "tt1", 7.8, 12345, 96), 7.8), (Rating(1, "tt1", 5.4, 99, None), None), (Rating(1, "tt1", None, None, 80), None)],
)
def test_imdb_hidden_below_100_votes(rating, shown):
    data = rating.as_dict()
    assert data["imdb"] == shown
    assert data["imdb_votes"] == rating.imdb_votes  # still available for tooltips


# --- RatingsClient against a local fake TMDB/OMDb ---------------------------------------


def client(session, fake_api):
    return RatingsClient(session, "tmdb-key", "omdb-key", tmdb_url=f"{fake_api.url}/3", omdb_url=f"{fake_api.url}/omdb/")


def search(*movies):
    return {"results": [dict(m) for m in movies]}


HALLOWEEN_1978 = {"id": 948, "title": "Halloween – Die Nacht des Grauens", "original_title": "Halloween", "release_date": "1978-10-24", "popularity": 30}
HALLOWEEN_2018 = {"id": 424139, "title": "Halloween", "original_title": "Halloween", "release_date": "2018-10-18", "popularity": 50}


async def test_match_by_title_and_year(session, fake_api):
    fake_api.add("GET", "/3/search/movie", search(HALLOWEEN_2018, HALLOWEEN_1978))
    movie = await client(session, fake_api).match("Halloween – Die Nacht des Grauens", 1978)
    assert movie["id"] == 948
    req = fake_api.sent("GET", "/3/search/movie")[0]
    assert req.query["language"] == "de-DE"
    assert req.query["year"] == "1978"
    assert req.query["api_key"] == "tmdb-key"


async def test_director_breaks_a_tie(session, fake_api):
    a = {"id": 1, "title": "Camouflage", "original_title": "Camouflage", "release_date": "2026-01-01", "popularity": 90}
    b = {"id": 2, "title": "Camouflage", "original_title": "Камуфляж", "release_date": "2026-03-01", "popularity": 5}
    fake_api.add("GET", "/3/search/movie", search(a, b))
    fake_api.add("GET", "/3/movie/1/credits", {"crew": [{"job": "Director", "name": "Someone Else"}]})
    fake_api.add("GET", "/3/movie/2/credits", {"crew": [{"job": "Director", "name": "Mykyta Gibalenko"}]})
    movie = await client(session, fake_api).match("Camouflage", 2026, ["Mykyta Gibalenko"])
    assert movie["id"] == 2


async def test_year_off_by_one_still_matches(session, fake_api):
    movie = {"id": 7, "title": "Bad Apples", "original_title": "Bad Apples", "release_date": "2026-02-01"}
    fake_api.add("GET", "/3/search/movie", search(movie))
    assert (await client(session, fake_api).match("Bad Apples", 2025))["id"] == 7


async def test_no_good_match(session, fake_api):
    other = {"id": 9, "title": "The ABC Saturday Morning Sneak Preview", "original_title": "x", "release_date": "1995-01-01"}
    fake_api.add("GET", "/3/search/movie", search(other))
    assert await client(session, fake_api).match("Sneak Preview", None) is None


async def test_search_falls_back_to_no_year(session, fake_api):
    def by_year(req):
        return 200, search() if "year" in req.query else search({"id": 3, "title": "Naza", "original_title": "NAZA", "release_date": "2026-05-01"})

    fake_api.add("GET", "/3/search/movie", handler=by_year)
    assert (await client(session, fake_api).match("Naza", 2026))["id"] == 3
    assert len(fake_api.sent("GET", "/3/search/movie")) == 2


async def test_lookup_parses_omdb(session, fake_api):
    fake_api.add("GET", "/3/search/movie", search({"id": 5, "title": "Primetime", "original_title": "Primetime", "release_date": "2026-09-24"}))
    fake_api.add("GET", "/3/movie/5/external_ids", {"imdb_id": "tt34206385"})
    fake_api.add("GET", "/omdb/", {"Response": "True", "imdbRating": "8.7", "imdbVotes": "1,234",
                                   "Ratings": [{"Source": "Internet Movie Database", "Value": "8.7/10"},
                                               {"Source": "Rotten Tomatoes", "Value": "86%"}]})
    rating = await client(session, fake_api).lookup("Primetime", 2026)
    assert rating == Rating(tmdb_id=5, imdb_id="tt34206385", imdb_rating=8.7, imdb_votes=1234, rotten_tomatoes=86)
    assert fake_api.sent("GET", "/omdb/")[0].query == {"apikey": "omdb-key", "i": "tt34206385"}


async def test_lookup_without_imdb_id(session, fake_api):
    fake_api.add("GET", "/3/search/movie", search({"id": 5, "title": "Kuzma", "original_title": "Kuzma", "release_date": "2026-01-01"}))
    fake_api.add("GET", "/3/movie/5/external_ids", {"imdb_id": None})
    assert await client(session, fake_api).lookup("Kuzma", 2026) == Rating(tmdb_id=5, imdb_id=None)
    assert not fake_api.sent("GET", "/omdb/")


async def test_rejected_keys(session, fake_api):
    fake_api.add("GET", "/3/configuration", {"status_message": "Invalid API key"}, status=401)
    with pytest.raises(RatingsAuthError) as err:
        await client(session, fake_api).validate()
    assert err.value.service == "tmdb"

    fake_api.responses.clear()
    fake_api.add("GET", "/3/configuration", {})
    fake_api.add("GET", "/omdb/", {"Response": "False", "Error": "Invalid API key!"})
    with pytest.raises(RatingsAuthError) as err:
        await client(session, fake_api).validate()
    assert err.value.service == "omdb"


async def test_server_error_is_retryable(session, fake_api):
    fake_api.add("GET", "/3/search/movie", status=503, body="busy")
    with pytest.raises(RatingsError) as err:
        await client(session, fake_api).match("Primetime", 2026)
    assert not isinstance(err.value, RatingsAuthError)


# --- RatingsManager (cache) ---------------------------------------------------------------

FILM = Film(id="p1", slug="p1", title="Primetime", release_year=2026, directors=("Lance Oppenheim",))
SNEAK = Film(id="p2", slug="p2", title="Sneak Preview", release_year=None)


async def manager(hass, lookup):
    entry = mock_entry()
    entry.add_to_hass(hass)
    client = RatingsClient(None, "t", "o")  # never used: lookup is patched
    with patch.object(client, "lookup", lookup):
        mgr = RatingsManager(hass, entry, client)
        await mgr.async_load()
        yield mgr


@pytest.fixture
def lookup():
    return AsyncMock(return_value=Rating(1, "tt1", 7.0, 500, 90))


async def test_manager_caches_and_skips_non_films(hass: HomeAssistant, lookup):
    async for mgr in manager(hass, lookup):
        await mgr.async_ensure([FILM, FILM, SNEAK], timeout=5)
        await mgr.async_ensure([FILM], timeout=5)
        assert lookup.await_count == 1  # deduplicated and then cached
        assert mgr.get("p1").imdb_rating == 7.0
        assert mgr.get("p2") is None


async def test_manager_refreshes_incomplete_ratings_daily(hass: HomeAssistant, lookup, freezer):
    lookup.return_value = Rating(1, "tt1", 6.0, 40, None)  # new release: no RT yet
    async for mgr in manager(hass, lookup):
        await mgr.async_ensure([FILM], timeout=5)
        freezer.tick(timedelta(hours=23))
        await mgr.async_ensure([FILM], timeout=5)
        assert lookup.await_count == 1
        freezer.tick(timedelta(hours=2))
        await mgr.async_ensure([FILM], timeout=5)
        assert lookup.await_count == 2


async def test_manager_disables_after_rejected_key(hass: HomeAssistant, lookup):
    lookup.side_effect = RatingsAuthError("omdb")
    async for mgr in manager(hass, lookup):
        await mgr.async_ensure([FILM], timeout=5)
        await mgr.async_ensure([Film(id="p3", slug="p3", title="Other", release_year=2020)], timeout=5)
        assert lookup.await_count == 1
        assert mgr.disabled_reason


async def test_manager_retries_after_temporary_error(hass: HomeAssistant, lookup):
    lookup.side_effect = [RatingsError("503"), Rating(1, "tt1", 7.0, 500, 90)]
    async for mgr in manager(hass, lookup):
        await mgr.async_ensure([FILM], timeout=5)
        assert mgr.get("p1") is None
        await mgr.async_ensure([FILM], timeout=5)
        assert mgr.get("p1") is not None


# --- integration: options step and get_program -----------------------------------------


@pytest.fixture
def program_api(freezer):
    freezer.move_to(NOW)
    with patch(f"{CLIENT}.get_showtimes", AsyncMock(return_value=showtimes())):
        yield


async def test_options_ratings_step(hass: HomeAssistant, program_api):
    entry = mock_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    with patch(f"{RATINGS}.validate", AsyncMock(side_effect=RatingsAuthError("omdb"))):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "ratings"})
        result = await hass.config_entries.options.async_configure(result["flow_id"], {CONF_TMDB_KEY: "t", CONF_OMDB_KEY: "bad"})
    assert result["errors"] == {"base": "invalid_omdb_key"}

    result = await hass.config_entries.options.async_configure(result["flow_id"], {CONF_TMDB_KEY: "t"})
    assert result["errors"] == {"base": "both_keys_needed"}

    with (
        patch(f"{RATINGS}.validate", AsyncMock()),
        patch(f"{RATINGS}.lookup", AsyncMock(return_value=Rating(1, "tt34206385", 8.7, 1234, 86))),
    ):
        result = await hass.config_entries.options.async_configure(result["flow_id"], {CONF_TMDB_KEY: " t ", CONF_OMDB_KEY: "o"})
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
        assert entry.data[CONF_TMDB_KEY] == "t"
        assert entry.runtime_data.ratings is not None

        response = await hass.services.async_call(DOMAIN, SERVICE_GET_PROGRAM, {}, blocking=True, return_response=True)
    film = response["showtimes"][0]["film"]
    assert film["id"] == PRIMETIME
    assert film["ratings"] == {"imdb_id": "tt34206385", "imdb": 8.7, "imdb_votes": 1234, "rotten_tomatoes": 86, "tmdb_id": 1}


async def test_program_without_ratings_keys(hass: HomeAssistant, program_api):
    entry = mock_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    response = await hass.services.async_call(DOMAIN, SERVICE_GET_PROGRAM, {}, blocking=True, return_response=True)
    assert response["showtimes"][0]["film"]["ratings"] is None
