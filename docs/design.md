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
2. ✅ **Ratings spike**: test TMDB/OMDb matching on a week of Hamburg films. Measure the hit rate, check the
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
5. ✅ **Login**: options menu (*Cinemas* | *Cineville account*) with the paste-the-code login (accepts the bare code,
   the `cineville://` URL or the whole `<input>` line) and logout (revokes the token); tokens in `entry.data`, updated on
   refresh. Separate `AccountCoordinator` (hourly): an auth error starts HA's reauth flow while the program keeps working.
   `get_program` marks `film.on_watchlist` / `film.seen` and `logged_in`; sensor *Watchlist films today*. Card: watchlist
   highlight or "only" toggle (remembered per browser), seen films dimmed/hidden, and all times/dates follow the HA
   profile (language, 12/24 h, local/server time zone, date format).
6. ✅ **Ratings in the integration**: options step *Ratings* (TMDB + OMDb keys, validated, stored in `entry.data`);
   `ratings.py` (matching rules from the spike, no HA imports) and `ratings_manager.py` (HA `Store` cache: complete
   7 days, incomplete 1 day, no match 3 days; 4 parallel lookups, max 800/day, disabled after a rejected key).
   Today's films are looked up after each program update; `get_program` waits up to 8 s for missing ones and returns
   `film.ratings` (`imdb` is null below 100 votes). Card: IMDb badge (links to IMDb) and Rotten Tomatoes badge, numbers in
   the HA locale. Live check on the preview fixture: 37/41 films matched, 14 IMDb ratings shown (6 hidden for < 100 votes), 17 RT.
7. ✅ **Packaging**: user-facing README (installation via HACS, options, card, action, troubleshooting, "unofficial"
   disclaimer); GitHub Actions (`.github/workflows/validate.yml`): hassfest, HACS validation, tests, card syntax check,
   and a weekly run of the API smoke test against the live Cineville API. Translation URLs moved into description
   placeholders (hassfest rule). Still open: license, a GitHub release (HACS shows versions from releases), screenshots,
   repository description/topics on GitHub (HACS validation checks them).
8. ✅ **Several accounts** (0.4.0): `entry.data["accounts"]` is a list (config entry version 2, migrated from the
   single account of version 1; helpers in `accounts.py`). One `AccountCoordinator` per account; an expired login
   starts re-authentication for *that* account (`async_start_reauth(data=…)`, wrong account rejected). Card: combined
   watchlists with coloured initials, filter all / anyone / everyone / one person (single account: the bookmark toggle),
   "seen" = seen by everyone, partly seen shows who. Seen films: show / dim / compact (one dimmed line with time(s)
   and title, no poster) / hide. `get_program` adds `accounts`, `film.watchlist_by`, `film.seen_by`.
   Also fixed: the card filed a program under the requested day even when the server returned a different "today".
9. ✅ **Login inside Home Assistant** (0.5.0): *Add an account* asks for the email address, Cineville emails a code,
   the user types it into HA; `auth.OtpLogin` drives Cineville's login pages with a private cookie session
   (see api/authentication.md). Re-authentication works the same way with the stored email prefilled and falls back
   to the manual paste method automatically if the pages changed; *Add an account manually* stays as a fallback.
   Accounts now also store the email address (for prefilling).
10. ✅ **Card loading** (0.5.0-alpha.3): the card is registered as a Lovelace *dashboard resource* (storage mode;
   created/updated with the version in the URL, duplicates removed, deleted with the last entry) instead of via
   `add_extra_js_url`. Dashboards wait for resources before drawing cards; the extra-JS route loaded in parallel, so on
   a fresh page load the card sometimes showed "Configuration error" until a reload. YAML-mode resources fall back to
   `add_extra_js_url`.
11. ✅ **Household and friends** (0.6.0): `entry.options["household"]` lists the household's user IDs (missing = every
   connected account; once chosen, new accounts start as friends; removing an account also removes it from the list).
   Friends' watchlists and seen films are reported (`watchlist_by`, `seen_by`, `accounts[].household = false`) and
   shown as outlined initials, but only the household counts for `film.seen`, the green stripe, the "whole household"
   filter and the *Watchlist films today* sensor. A film only a friend wants gets no stripe, just the friend's marker.
