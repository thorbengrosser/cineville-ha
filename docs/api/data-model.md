# Data model

Taken from the zod schemas in the website's API client, and the JSON Schemas served at
`GET /production-types/film`. Field names are exactly as returned.

Every object has `createdAt` / `updatedAt` (ISO UTC) and `_links.self.href`. "Attributes" fields are
free-form per production type; their shapes come from the production-type JSON Schemas.

## Event

One screening of a film in a venue. [Sample](samples/event-with-embeds.json).

| Field | Type | Notes |
|---|---|---|
| `id` | uuid | |
| `productionId` | uuid \| null | **null for unmatched imports**. Filter them out with `productionId.isNull=false` |
| `productionTypeId` | string | always `"film"` |
| `productionHint` | `{title: string\|null, universalIds: [{type, value}]}` | Raw title and IDs from the cinema's ticketing system (e.g. `"Primetime 3.W."`, `{type: "POS"}` / `"COMSCORE"`) |
| `venueId` | uuid | |
| `startDate` | ISO UTC | |
| `endDate` | ISO UTC \| null | Can be null; see [display-logic.md](display-logic.md#end-time) |
| `ticketingUrl` | url \| null | Deep link to the cinema's ticket shop (often kinoheld.de) |
| `isHidden` | bool | |
| `attributes.languageVersion` | string \| null | `"original"`, a locale code for dubbed versions (`"de-DE"`, seen `"en-GB"`, `"fa"`), or missing/null. Share in one month in Germany: original 404, null 395, de-DE 198 |
| `attributes.subtitles` | string[] | Locale codes, e.g. `["de-DE"]`, `["en-GB"]` |
| `attributes.tags` | string[] | `3d`, `70mm`, `classic`, `modernClassic`, `special`, `englishSubs`, `preview`, `sneakPreview` |
| `localizableAttributes.customTags` | string[] | Free-text tags written by the cinema |
| `_links` | `{self, production?, productionType, venue}` | |
| `_embedded` | `{production?, venue?, productionType?, collections?}` | Only with `embed` |

⚠️ `attributes` is often just `{}` (no language info at all), and sometimes
`{"languageVersion": null, "subtitles": [], "tags": []}`.

## Production

A film. [Sample](samples/production.json).

| Field | Type | Notes |
|---|---|---|
| `id` | uuid | |
| `slug` | string | Website URL: `https://cineville.de/de-DE/filme/<slug>` |
| `title` | string | |
| `productionTypeId` | `"film"` | |
| `universalIds` | `[{type, value}]` \| null | `COMSCORE`, `MACCSBOX`, `BIOGUIDEN`, `BIOTELLER`. No IMDb/TMDB IDs |
| `assets.poster` / `.cover` / `.trailer` | Asset \| undefined | See [Asset](#asset). Poster is portrait, cover is landscape (16:9 still) |
| `attributes.duration` | int | minutes |
| `attributes.directors`, `.cast` | string[] | |
| `attributes.releaseYear` | int | (but filter it as a string) |
| `attributes.premiereDate` | `YYYY-MM-DD` \| null | German cinema release |
| `attributes.spokenLanguages` | string[] | Locale codes, e.g. `["en"]` |
| `attributes.contentRatingMinimumAge` | int \| null | FSK |
| `attributes.highlights` | `[{type, author?, startDate?, endDate?}]` | `type` ∈ `filmOfTheWeek`, `tip`, `upcomingFilm`, `freshTrailer` |
| `localizableAttributes.shortDescription` | string | One-liner. Good for the HA card |
| `localizableAttributes.description` | string | Full synopsis |
| `localizableAttributes.editorsNote` | string | |
| `localizableAttributes.highlightDescriptions` | `{tip, filmOfTheWeek}` | |
| `_links.events` | | `/productions/{id}/events` |

## Venue

A cinema. [Sample](samples/venues-list-response.json).

| Field | Type | Notes |
|---|---|---|
| `id` | uuid | Stable. The 2025 IDs still work in 2026 |
| `name` | string | e.g. `"Studio Kino"` |
| `slug` | string | |
| `address` | `{street, houseNumber, postalCode, city, country, latitude, longitude}` | Strings have stray trailing spaces, so `strip()` them. lat/lon can be null |
| `isHidden` | bool | |
| `assets.cover` | Asset | |
| `attributes.website` | url | |
| `localizableAttributes` | `{intro, shortDescription, description, ticketInfo}` | |

City membership is not a field on the venue; it's a collection (`GET /venues/{id}/collections` → `cities/hamburg`).

### Hamburg venues (2026-10)

| Name | ID |
|---|---|
| 3001 Kino | `800f1df6-26e9-43b9-9995-8fc48f71cdf1` |
| Abaton-Kino | `c9737ff8-be52-4f9b-a183-5eb8794e9944` |
| Alabama Kino | `23df7bf4-7f5e-4590-ab7a-90e33f03ce8d` |
| B-Movie | `7978be1e-4989-4f84-9e2a-69ec059a05d0` |
| filmRaum | `2fe359c5-a843-4de2-9660-74be24edff6d` |
| filmRaum Open Air Kino | `320eafc7-5806-40c7-8a72-7bea03e9cc0a` |
| Kurzfilm Festival Hamburg | `23eeba21-ac59-46b8-9932-db43b31d3ca2` |
| Metropolis im Planet Harburg | `eebf8d42-f316-4e39-9014-b7e9f3f48174` |
| Metropolis Kino Hamburg | `db1fee7e-3f5d-4f2b-9c4e-9bcd5db83867` |
| nestkino | `1d7fc921-eff6-496e-ae7f-503c3ffbec3c` |
| Studio Kino | `88beb28b-cec3-43f8-b1f2-eeb7d58c1a6b` |
| zeise kinos | `6da13ac1-5b70-40db-b917-ed61202a9960` |
| Zeise Open Air | `9316640c-1ee4-47dc-bfa2-a4a8024400ac` |

## Asset

```json
{"id": "uuid", "url": "https://culturekit-assets.imgix.net/7/assets/<uuid>.jpg",
 "mimeType": "image/jpeg | image/png | image/bmp | video/mp4", "createdAt": "...", "updatedAt": "..."}
```

URLs are on **imgix**, so they can be resized on the fly. The website uses `?auto=format&fit=max&w=384&q=100`.
Trailers (`.mp4`) need `?fm=mp4` for playback.

## Collection / CollectionGroup

```json
{"id": "hamburg", "collectionGroupId": "cities", "_links": {"self": {"href": "/collections/hamburg"}, "collectionGroup": {...}}}
```

See [endpoints.md](endpoints.md#collections-tagging-and-grouping) for the useful IDs.

## Rating

`GET /ratings/by-production/{id}` → `{"rating": 3.32, "count": 151}`.

## List envelope

```json
{"count": 2, "totalCount": 58,
 "_links": {"self": {"href": "..."}, "next": {"href": "...&page[after]=<cursor>"}, "previous": {"href": "..."}},
 "_embedded": {"events": [ ... ]}}
```

The `_embedded` key is the plural resource name: `events`, `productions`, `venues`, `collections`,
`collectionGroups`, `productionTypes`, `assetRelations`, `products`, `orderForms`.
