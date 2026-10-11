# Cineville API (reverse-engineered)

Unofficial documentation of the API behind [cineville.de](https://cineville.de), reconstructed from the
website's JavaScript bundles and checked against the live API.

> **Status:** Unofficial and undocumented by Cineville. It can change without notice: the previous
> GraphQL endpoint (`https://cineville.de/api/graphql`) was removed in 2026 without warning.
> Last verified: **2026-10-11** against website build `szM2pebHIRg6yRza574sf`.
> Run [`smoke_test.py`](smoke_test.py) to check whether the assumptions below still hold.

## Contents

| File | What's in it |
|---|---|
| [endpoints.md](endpoints.md) | Every endpoint, public and authenticated, with methods and parameters |
| [authentication.md](authentication.md) | OIDC login, tokens, and options for logging in from Home Assistant |
| [querying.md](querying.md) | Filter syntax, operators that work (and those that are silently ignored), sorting, pagination, embeds, locale |
| [data-model.md](data-model.md) | Event / Production / Venue / Collection / Asset objects, attribute enums |
| [display-logic.md](display-logic.md) | How cineville.de turns raw data into what you see (language labels, end times, "today", specials) |
| [samples/](samples/) | Real responses (trimmed) |
| [smoke_test.py](smoke_test.py) | Stdlib-only script that checks the API still behaves as documented |

## The short version

- **Base URL:** `https://api.cineville.de`. This is "CultureKit", the platform behind Cineville in NL, BE, DK, SE and DE.
  The German site points at this host. The data is scoped to the German catalogue (e.g. 21 German city collections).
- **No authentication** for public schedule data (events, productions, venues, collections, ratings).
  Member data (watchlist, seen films, check-ins, reservations, card, subscription) needs an OIDC bearer token.
  See [authentication.md](authentication.md).
- **CORS is open** (`Access-Control-Allow-Origin: *`). No rate-limit headers were observed. Be polite anyway.
- **HAL-style JSON:** lists look like `{count, totalCount, _links: {self, next?, previous?}, _embedded: {<resource>: [...]}}`.
- **Cursor pagination:** follow `_links.next.href`. Max `page.limit` is **1000**.
- **Search endpoints are `POST`** with a JSON filter body (`/events/search`, `/productions/search`).
  Plain `GET` list endpoints accept the same filters as bracket-style query params.
- ⚠️ **Unknown filter keys and operators are silently ignored.** A typo returns *everything* instead of
  an error. See [querying.md](querying.md#operators) for the verified list.

## Quick start: today's showtimes in a set of cinemas

```bash
curl -s -X POST https://api.cineville.de/events/search \
  -H 'Content-Type: application/json' \
  -d '{
    "productionId": {"isNull": false},
    "isHidden":     {"eq": false},
    "startDate":    {"gte": "2026-10-11T16:00:00.000Z", "lt": "2026-10-12T02:00:00.000Z"},
    "venueId":      {"in": ["88beb28b-cec3-43f8-b1f2-eeb7d58c1a6b", "c9737ff8-be52-4f9b-a183-5eb8794e9944"]},
    "embed":        {"production": true, "venue": true},
    "sort":         {"startDate": "asc"},
    "page":         {"limit": 100}
  }'
```

All the showtimes in a city: replace `venueId` with `"venue": {"collection": {"cities": {"in": ["hamburg"]}}}`.

Next page: `POST` the **same body** to `https://api.cineville.de` + `_links.next.href`.
With curl, pass `-g` because the href contains `[` `]`.

## Other hosts seen in the bundle

| Host | Purpose | Relevant for us? |
|---|---|---|
| `api.cineville.de` | Schedule, catalogue, user data, shop (CultureKit) | **Yes**. Everything in these docs |
| `cms.cineville.de` | Strapi CMS: magazine articles, festivals, FAQ, page content, and the city list shown in filters. Needs a bearer token that ships in the public JS bundle | Not needed. Cities are also available as collections |
| `mein.cineville.de` | Account self-service portal ("Konto verwalten") | No. Login itself happens on `api.cineville.de` (OIDC), see [authentication.md](authentication.md) |
| `culturekit-assets.imgix.net` | Images and trailers (imgix CDN, supports resize params) | Yes, for posters |
| `cineville.de/api/auth/*` | NextAuth session for the website (holds the user's CultureKit bearer token) | No |
| `cineville.de/api/tenants` | **Public per-country config** used by the mobile app: API URLs, OAuth client IDs, timezone, `scheduleWeek` (DE: day starts at `startHour: 4`, which confirms the 04:00 boundary), `disabledFeatures` (DE: `notifications`) | Yes: client ID for login, see [authentication.md](authentication.md) |

## How this was reconstructed

1. Downloaded every chunk listed in `https://cineville.de/_next/static/<buildId>/_buildManifest.js`.
2. The API client is in `pages/_app-*.js`. Each resource is a class like
   `new tv(axios, "/venues", {get, list, createInput, ...})`, and every response is validated with
   **zod schemas** that sit right next to it. Those schemas are the source for [data-model.md](data-model.md).
3. The page chunks (`pages/showtimes-*.js`, `pages/films-*.js`, ...) show which filters the website actually sends.
4. Every filter, operator and endpoint was then checked against the live API by comparing `totalCount`s.

When it breaks again, repeat the same steps: grep the new `_app-*.js` for `super(e,"/` and `new tv(e,"/` to find the resources.
