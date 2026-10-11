# Querying: filters, operators, sort, pagination, embeds, locale

## Request shape

`POST /events/search` and `POST /productions/search` take one JSON object. The control keys
(`page`, `sort`, `embed`) sit next to the filter fields:

```json
{
  "startDate": {"gte": "2026-10-11T16:00:00.000Z", "lt": "2026-10-12T02:00:00.000Z"},
  "venue":     {"collection": {"cities": {"in": ["hamburg"]}}},
  "page":      {"limit": 100},
  "sort":      {"startDate": "asc"},
  "embed":     {"production": true, "venue": true}
}
```

`GET` list endpoints take the same structure as bracket query params, serialised the way
[`qs`](https://github.com/ljharb/qs) does it:

```
GET /venues?collection[cities][in][0]=hamburg&isHidden[eq]=false&sort[name]=asc&page[limit]=1000
```

All timestamps are ISO-8601 **UTC** (`...Z`). Date-only fields (`premiereDate`, `releaseYear`) are strings.

## ⚠️ The big gotcha: unknown keys are ignored

The API validates the *types* of fields it knows (`releaseYear: {eq: 2026}` → 400 "expected string"),
but **unknown fields and unknown operators are dropped without an error**. `{"bogus": {"eq": 1}}` returns all
274,982 events. Always check `totalCount` when you try a new filter. Only use the combinations below.

## Operators

Verified 2026-10-11 by comparing `totalCount` against a baseline.

| Operator | Works | Example |
|---|---|---|
| `eq` | ✅ | `{"venueId": {"eq": "<uuid>"}}` |
| `neq` | ✅ | `{"venueId": {"neq": "<uuid>"}}` |
| `ne` | ❌ ignored | use `neq` |
| `in` | ✅ | `{"venueId": {"in": ["<uuid>", "<uuid>"]}}` |
| `nin` | ✅ | `{"productionId": {"nin": [...]}}` |
| `gt` / `gte` / `lt` / `lte` | ✅ | `{"startDate": {"gte": "...", "lt": "..."}}` |
| `isNull` | ✅ | `{"productionId": {"isNull": false}}` |
| `contains` (array field) | ✅ | `{"subtitles": {"contains": ["en-GB"]}}`, `{"tags": {"contains": ["preview"]}}` |
| `contains` (string field) | ✅ case-insensitive substring | `{"title": {"contains": "rime"}}` |
| `like` / `ilike` | ❌ ignored | use `contains` |

Several operators can be combined on one field (`{"premiereDate": {"isNull": false, "gt": "2026-10-11"}}`).

## Event filters (`POST /events/search`)

| Field | Verified | Notes |
|---|---|---|
| `startDate` | ✅ | Range on screening start. Basically required: without it you search all history (275k events) |
| `endDate` | ✅ | |
| `venueId` | ✅ | `eq` / `neq` / `in` / `nin` |
| `productionId` | ✅ | `eq` / `in` / `nin` / `isNull`. **Always send `{"isNull": false}`**: ~8% of events are unmatched imports with only a `productionHint` (raw title from the cinema's POS) and no film data |
| `isHidden` | ✅ | The website always sends `{"eq": false}` |
| `ticketingUrl` | ✅ | `isNull` |
| `venue.collection.<group>` | ✅ | `{"venue": {"collection": {"cities": {"in": ["hamburg", "koeln"]}}}}`. City IDs are case-sensitive |
| `collection.<group>` | ⚠️ applied | Event-level collections (festivals/series), e.g. `{"collection": {"events-hamburg": {"in": ["filmfest-hamburg"]}}}`. The filter is applied (counts drop), but no positive match was found during testing because no active series were picked. Use `embed.collections` to discover real IDs |
| `tags` | ✅ | `contains`. Values: `3d`, `70mm`, `classic`, `modernClassic`, `special`, `englishSubs`, `preview`, `sneakPreview` |
| `subtitles` | ✅ | `contains`, with locale codes like `de-DE`, `en-GB` |
| `languageVersion` | ❌ ignored | Filter on the client side instead (top-level and `attributes.languageVersion` are both ignored) |
| `production.title` | ⚠️ unclear | Changed the count, but not in a way consistent with filtering. Don't rely on it; filter by `productionId` |

## Production filters (`POST /productions/search`)

| Field | Verified | Notes |
|---|---|---|
| `id`, `slug`, `title` | ✅ | `title.contains` = case-insensitive substring |
| `premiereDate` | ✅ | Date string `YYYY-MM-DD`. "Coming soon" = `{"isNull": false, "gt": "<today>"}` |
| `releaseYear` | ✅ | **String**: `{"eq": "2026"}` |
| `collection.<group>` | ✅ | `{"collection": {"common": {"in": ["now-screening"]}}}` |
| `event` | ✅ | Nested **event filter**: "films that have a matching screening", e.g. `{"event": {"isHidden": {"eq": false}, "startDate": {...}, "venue": {"collection": {"cities": {"in": ["hamburg"]}}}}}` |
| `attributes.*` | ❌ ignored | |

## Venue filters (`GET /venues`)

`collection[cities][in][]`, `isHidden[eq]`, `sort[name]`, `page[limit]` (the website uses exactly these).

## Sorting

`"sort": {"<field>": "asc" | "desc"}`. Unknown sort fields are ignored.

| Resource | Sort fields used by the website |
|---|---|
| events | `startDate` ✅ |
| productions | `title` ✅, `createdAt`, `premiereDate` |
| venues | `name` |

## Pagination

- `"page": {"limit": N}`, with **1 ≤ N ≤ 1000** (`>1000` → 400). Default is 100.
- The response has `_links.next.href`, e.g. `/events/search?page[limit]=100&page[after]=<cursor>`.
  The cursor is base64 JSON of the last row's sort key (`{"startDate":..., "createdAt":..., "id":...}`).
- **For search endpoints, re-`POST` the same body to the `next` href.** The href carries the cursor; the body still carries the filters.
- `previous` exists too. Pagination ends when `next` is absent.
- `count` = items on this page, `totalCount` = total matches.

## Embeds

`"embed": {"production": true, "venue": true}` inlines the related objects under each event's `_embedded`.
This saves N+1 requests, so always use it for showtimes. `"productionType": true` and `"collections": true`
also work (✅) and add `_embedded.productionType` / `_embedded.collections` (the event's series/festival collections).

On `GET` endpoints: `?embed[production]=true&embed[venue]=true`.

## Locale

The `locale` request header controls `localizableAttributes` (descriptions etc.):

| `locale` header | Result |
|---|---|
| *(none)* or `de-DE` | German strings |
| `en-GB` | Same keys with **empty strings**. There is no English copy in the DE catalogue |
| `*` | All locales: `{"de-DE": {"description": ...}}` (see [samples/production-locale-star.json](samples/production-locale-star.json)) |

The website sends `de-DE` or `en-GB` depending on the UI language, and `*` when it wants to fall back.
**Recommendation: send nothing (or `de-DE`).**

## Filters the website sends

### Showtimes page (`/de-DE/programm`)

Built in `pages/showtimes` → `48545.c`. The site always adds `productionId.isNull=false`, `isHidden.eq=false`,
`embed.production/venue`, and `sort.startDate=asc`:

```js
{
  collection:   { <group>: { in: [...] } },     // series/festival filter
  productionId: { eq: <film>, in: <watchlist ids>, nin: <seen ids> },
  venueId:      { in: [...] },                  // "Kinos" filter
  startDate:    { gte: <day start or now>, lt: <next day 04:00 local> },
  venue:        { collection: { cities: { in: [...] } } },
  tags:         { contains: [...] },
  subtitles:    { contains: [...] },
  page:         { limit: 20 }
}
```

### Films page

`POST /productions/search` with `{event: {isHidden: {eq: false}, startDate: {gte: <now>, lte: <+N days>}, venue: {collection: <cities>}}, sort: {title: "asc"}, page: {limit: 21}}`.

### Coming soon

`POST /productions/search` with `{premiereDate: {isNull: false, gt: "<today>"}, sort: {premiereDate: "asc"}, page: {limit: 21}}`.

### Cinemas page

`GET /venues?collection[cities][in][]=...&isHidden[eq]=false&sort[name]=asc&page[limit]=1000`.
