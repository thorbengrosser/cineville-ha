# cineville-ha: design

Status: agreed direction (2026-10-11), nothing built yet.

## Goal

A Home Assistant integration + dashboard card that shows the Cineville program for a day in a chosen city,
with posters, IMDb / Rotten Tomatoes ratings, cinema/time filters, and (when logged in) watchlist features.

## Decisions

| Topic | Decision |
|---|---|
| Packaging | One HACS repo, `custom_components/cineville`. The integration serves its own card JS and registers it as a frontend resource, so there's a single install |
| Day | Default **today**, with a day picker for the next few days. A day runs **04:00–04:00** local (`scheduleWeek.startHour` from `/api/tenants`) |
| Card layout | **Switchable**: grouped by film (poster, title, ratings, time chips) ⇄ chronological list (one row per screening) |
| Filters | City (setup), cinemas (setup default + card filter), "from time" (card filter). Filtering happens in the card, on one day's data |
| Watchlist | With login: "watchlist only" toggle or highlighting. Already-seen films (`visit-history`) dimmed or hidden |
| Login | Optional. Mobile-app public client + PKCE, code pasted from the `form_post` page, refresh token stored. See [api/authentication.md](api/authentication.md). Needs a reauth flow |
| Ratings | Optional, two free user-supplied keys: **TMDB** (German title + year (+ director) → IMDb ID) and **OMDb** (IMDb ID → IMDb rating + Rotten Tomatoes). Cached per production. Without keys there are no badges |

## Data flow

```
config entry ── city, venue IDs, (refresh token), (TMDB/OMDb keys)
  │
  ├─ ShowtimesCoordinator   every ~30 min   POST /events/search  (city or venueId.in, day window, embed production+venue)
  │                                          → flattened showtimes (display-logic.md: language label, end time, specials)
  ├─ AccountCoordinator     every ~60 min   watchlist/production-ids, visit-history/production-ids  (only if logged in)
  └─ RatingsCache           on demand       per productionId: TMDB match → OMDb ratings, stored via HA Store, refreshed ~weekly
```

The card gets its data through a **service with response** (e.g. `cineville.get_program` with `day`), not through
entity attributes: a day's program easily exceeds the recorder's 16 KB attribute limit.

## Entities

- `sensor.cineville_<city>_screenings_today`: count, plus a short attribute summary
- `sensor.cineville_<city>_watchlist_today`: watchlist films showing today (logged in only), for automations and notifications
- (later) `calendar.cineville_<city>`: screenings as calendar events

## Ratings spike results (2026-10-11, Hamburg, next 7 days)

[`tools/ratings_spike.py`](../tools/ratings_spike.py) on 47 Cineville productions:

| | Count | Notes |
|---|---|---|
| Not a film | 4 | Sneak Preview ×2, Sneak Extreme, Shortfilm Slam: `releaseYear` 0. **Skip matching when `releaseYear` is missing or 0** |
| TMDB matched | **40 of 43 real films (93%)** | All spot-checked matches had the right director, including German titles of foreign films (*Pans Labyrinth* → *El laberinto del fauno*, *Shaun das Schaf – Spuk im Kürbisfeld* → *Shaun the Sheep: The Beast of Mossy Bottom*) |
| Not matched | 3 | Small festival/docs not on TMDB (*Kuzma*, *Materia Prima*, *Songs of Hope and Despair*) |
| IMDb rating available | 23 | Missing mostly for brand-new German releases with too few votes |
| Rotten Tomatoes available | 19 | Mostly international titles; German releases rarely have RT |

Matching rules (keep in the real implementation):
- Search TMDB `/search/movie` with `language=de-DE` and `year=releaseYear`, then without a year as fallback.
  Strip a trailing `(2026)` from Cineville titles.
- Score: normalized title equals TMDB `title` or `original_title` → +3; same year → +2, ±1 year → +1, otherwise −2;
  director overlap (TMDB credits vs Cineville `directors`) → +3 (checked on the top 3 candidates). Accept at score ≥ 4.
- Normalization must transliterate letters NFKD can't decompose (ł, ø, ß, æ, …). This bug made *Vaterland*
  (Paweł Pawlikowski) look like a director mismatch.
- Cineville's `releaseYear` can be off by one from TMDB's (*Bad Apples* 2025 vs 2026), hence the ±1 tolerance.

Display rules (decided): **hide the IMDb rating when `imdbVotes` < 100** (too noisy). No TMDB-rating fallback for now.

Implications for the card: badges will often be missing for new German films, so the layout must look fine without
them. Ratings for new releases change quickly, so cache missing ratings for a short time (~1 day) and found ones for longer (~1 week).

## Milestones

1. ✅ **API client** (`custom_components/cineville/`: `api.py`, `auth.py`, `models.py`; plain async `aiohttp`, no HA imports):
   showtimes for a day, cities, venues, tenant config, account endpoints, token exchange/refresh/revoke.
   50 tests against a local fake server (`tests/`, run with `.venv/bin/python -m pytest`). Checked against the live
   API on 2026-10-11. Note: the tenant config says `Europe/Amsterdam` for DE; we default to `Europe/Berlin` (same rules).
2. **Ratings spike**: test TMDB/OMDb matching on a week of Hamburg films. Measure the hit rate, check the
   German-title and year edge cases. Decide on the matching rules before building on them.
3. ✅ **Integration skeleton**: config flow (city → cinemas, options flow to change cinemas), coordinator
   (today every 30 min; other days on demand, cached 30 min), sensors (`Upcoming screenings today`, `Next screening`,
   re-evaluated every minute), `cineville.get_program` service (`date` up to 7 days ahead, returns `Showtime.as_dict()`
   list), EN/DE translations, `hacs.json`. 16 HA tests via `pytest-homeassistant-custom-component` (HA 2026.10.1).
4. ✅ **Card** (`custom_components/cineville/frontend/cineville-card.js`, dependency-free web component, served by the
   integration and auto-loaded via `add_extra_js_url`): grouped/list views (choice remembered per browser), day picker,
   cinema and "from" time filters, posters (imgix-resized), highlight/specials/language badges, ticket links, DE/EN,
   visual editor (`getConfigForm`). Rating badges get a placeholder slot (`.ratings`), filled in milestone 6.
   Preview without HA: `dev/preview.html` with the recorded fixture `dev/fixtures/program-hamburg.json`.
5. **Login**: config/options flow with the paste-the-code step, account coordinator, watchlist UI, reauth.
6. **Ratings in the integration**: options flow for keys, cache, badges.
7. HACS packaging, README, screenshots.
