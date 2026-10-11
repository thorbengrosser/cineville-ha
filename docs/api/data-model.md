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

### All venues (2026-10-11)

`GET /venues?page[limit]=1000` with no filter returns every venue in the German catalogue: 77 venues, 74 of them visible.
The 15 city collections below are the ones that have venues. They match the city filter on cineville.de exactly
(`client.get_cities()` returns the same 15). The other city collection IDs (`Nürnberg`, `k`, `nu`, `neue-kinos`, `dresden`,
`erlangen`) have no venues, apart from `Nürnberg`, whose 2 venues are also in `nuernberg`.

⚠️ Some venues are **not in any city collection**, so a city filter never returns them. They don't show up on the
website's city-filtered pages either, and at the time of writing none of them has upcoming screenings.
Leipzig appears to be set up but not launched (its 3 venues are all hidden and there's no `leipzig` collection).

#### Aachen (`aachen`)

| Name | ID |
|---|---|
| Apollo Kino & Bar | `0210a2ae-1517-4f8b-b537-ab9d259fb129` |

#### Berlin (`Berlin`)

| Name | ID |
|---|---|
| b-ware!ladenkino | `eb5cc5a4-1564-4971-9f2f-54fce581fe46` |
| Bali Kino | `193b1bf8-7e8f-4d9c-8047-429d032eb9e1` |
| BrotfabrikKINO | `d89edbf1-77f0-4bbf-9c2b-b78d1c9c6708` |
| City Kino Wedding | `e328d599-0b4a-4911-9822-1722e9e5cee0` |
| Filmkunst 66 | `e86cd374-7e92-47e6-8d06-653f55f408f1` |
| Filmrauschpalast | `f94887cf-bce5-4cf6-947f-b06d8e64a5fb` |
| Freiluftkino Hasenheide ¹ | `ae2fcf19-7d70-49c1-ae10-59a5fc599855` |
| Freiluftkino Insel @Atelier Gardens ¹ | `c3ee4acd-cb8b-4b40-a79c-5870f88da688` |
| Freiluftkino Rehberge ¹ | `7f9013c1-60b7-4d7e-b51d-a5ded44bbaaa` |
| fsk Kino | `9cc2fa73-ee4f-487b-9af0-b3003447de28` |
| Hackesche Höfe Kino | `8dfb4317-395f-42fd-abed-c3561bba89ea` |
| hofkino.berlin ¹ | `6ea2585f-dcb2-4028-b268-e86e514dca2a` |
| Il Kino | `46df7e0c-99a8-4a7e-ae90-8cded0d6d8ea` |
| Klick Kino | `8871c731-a21a-4ad9-a713-24341fda616d` |
| Sputnik Kino | `92f9ac95-ff89-4877-8af6-3c487058cfb7` |
| Wolf Kino | `3f6e47fc-a3d7-4e9f-af97-01d7b825f1c7` |

#### Bonn (`bonn`)

| Name | ID |
|---|---|
| Bonner Kinemathek | `c7a20a8c-bc46-4d80-bd87-d8b6c1d02a44` |
| Neue Filmbühne Beuel | `441ab869-cfa7-48d6-b00d-f06ce5b2f7c1` |
| Rex-Lichtspieltheater | `71b2e207-e616-4ec6-bc09-47e237460d9b` |

#### Braunschweig (`braunschweig`)

| Name | ID |
|---|---|
| Universum Filmtheater | `af33f8f0-812c-41ac-93e6-96d8974c2b8d` |

#### Bremen (`bremen`)

| Name | ID |
|---|---|
| Atlantis | `df1519f6-8f5b-4f84-91ea-944265fdcdc7` |
| Cinema Ostertor | `d215339e-2765-44ec-9719-4954a1be94de` |
| City 46 | `936f09cd-57df-45db-a8d4-99fdb4974524` |
| Gondel | `baac23f8-9ea7-4569-9772-6eda722cd7e2` |
| Schauburg | `1b4d2ee0-1d07-40f6-a767-a75fd5d9bae2` |

#### Düsseldorf (`duesseldorf`)

| Name | ID |
|---|---|
| atelier Kino im Savoy Theater | `6cd7343d-e036-4cb2-88bf-a58aca3e170c` |
| Bambi Filmstudio | `0ab054c3-d1f5-4f9a-b594-e9cb47bed16c` |
| Cinema Düsseldorf | `c0d33fe6-740b-4b52-9d6a-9646c4bacdd0` |
| Metropol Filmkunstkino | `9457da8e-5d32-4c6d-8f1e-8f3b5fef7bd6` |

#### Freiburg (`freiburg`)

| Name | ID |
|---|---|
| Friedrichsbau | `a8efb10a-55c2-4f24-a019-c29d74b02133` |
| Harmonie | `fdd080cf-2f84-4c81-8f65-dcff61959991` |
| Kandelhof | `6f6b9dac-5316-4c1d-ac8b-a70d42cd7885` |
| Kommunales Kino Freiburg | `b6dde99f-6191-4bb4-81a1-53425dc2af8d` |

#### Fürth (`fuerth`)

| Name | ID |
|---|---|
| Babylon - Kino am Stadtpark | `ce1e157b-244e-4762-ac2e-4275278c0c92` |
| Uferpalast | `82cd5b6e-cd0a-4ed7-a838-95f184b14679` |

#### Hamburg (`hamburg`)

| Name | ID |
|---|---|
| 3001 Kino | `800f1df6-26e9-43b9-9995-8fc48f71cdf1` |
| Abaton-Kino | `c9737ff8-be52-4f9b-a183-5eb8794e9944` |
| Alabama Kino ¹ | `23df7bf4-7f5e-4590-ab7a-90e33f03ce8d` |
| B-Movie | `7978be1e-4989-4f84-9e2a-69ec059a05d0` |
| filmRaum | `2fe359c5-a843-4de2-9660-74be24edff6d` |
| filmRaum Open Air Kino ¹ | `320eafc7-5806-40c7-8a72-7bea03e9cc0a` |
| Kurzfilm Festival Hamburg ¹ | `23eeba21-ac59-46b8-9932-db43b31d3ca2` |
| Metropolis im Planet Harburg | `eebf8d42-f316-4e39-9014-b7e9f3f48174` |
| Metropolis Kino Hamburg | `db1fee7e-3f5d-4f2b-9c4e-9bcd5db83867` |
| nestkino | `1d7fc921-eff6-496e-ae7f-503c3ffbec3c` |
| Studio Kino | `88beb28b-cec3-43f8-b1f2-eeb7d58c1a6b` |
| zeise kinos | `6da13ac1-5b70-40db-b917-ed61202a9960` |
| Zeise Open Air ¹ | `9316640c-1ee4-47dc-bfa2-a4a8024400ac` |

#### Köln (`koeln`)

| Name | ID |
|---|---|
| Cinenova | `2fe8970f-c064-4789-9340-f6149dc40ffd` |
| Filmhaus Köln | `73754bc1-a9d1-4c79-b702-793e0eb3ccc6` |
| Filmpalette | `6e5de7e1-de0f-4aa8-af79-a49be5f98446` |
| KFFK / Kurzfilmfestival Köln ¹ | `6c828ed9-f64c-4f44-a9ef-61bfdda130a5` |
| Lichtspiele Kalk | `fe4ba487-5fec-4a61-ae77-f36b01b277fa` |
| Metropolis Köln | `5322b27b-ce62-4592-9968-fd401e94f8e2` |
| Odeon Köln | `76bb73f4-17d4-4014-b479-0cf53914525e` |
| Odonien ¹ | `d660b4e1-2651-4da0-ad96-39ebf8f1fef3` |
| OFF Broadway | `cbbd0e34-5357-4e39-a9c9-750f834b73fa` |
| Rex am Ring | `8b3f8b34-2c01-42fb-b6b3-4f643615e750` |
| Weisshaus Kino | `f43cdcca-5b3e-4211-b8dd-af004d953325` |

#### Leverkusen (`leverkusen`)

| Name | ID |
|---|---|
| Scala Cinema | `71d79797-17f4-42fc-a250-b2e89f53b475` |

#### Nürnberg (`nuernberg`)

| Name | ID |
|---|---|
| Casablanca Filmkunsttheater | `3ddc1eb4-8538-4fa6-8bcc-32e0851e31d4` |
| Filmhaus im KunstKulturQuartier | `825993c9-9193-42b1-b332-b618279e02fa` |
| KommKino | `7d605b4f-ee8c-457b-8493-cbe7319534ce` |
| Meisengeige | `c28ca3ed-7f47-43e8-b3ef-8828f95e3b37` |
| Metropolis Nürnberg | `54e546a5-e621-4497-969c-0d81cb2954bf` |

#### Potsdam (`potsdam`)

| Name | ID |
|---|---|
| Thalia Potsdam | `c144871b-4264-4146-a553-1be9390f3df9` |

#### Wuppertal (`wuppertal`)

| Name | ID |
|---|---|
| Cinema | `2ece6337-083c-49ba-9279-a99bbe9cee25` |
| Rex | `d152eb78-3daa-4588-8b25-52357e4683f4` |

#### Würzburg (`wuerzburg`)

| Name | ID |
|---|---|
| Central im Bürgerbräu | `6cee9ccd-c2df-4558-bb4e-8987f77d6443` |
| Kino Central Open Air ¹ | `0f53af37-bff9-48e9-b749-6f98d233a0e7` |

#### Not in any city collection

| Name | ID | Address city | Hidden |
|---|---|---|---|
| Cinémathèque Leipzig ¹ | `cfcfa9f9-ea1e-4b8a-b5e3-a519c25f9711` | Leipzig | yes |
| E-Werk Kino ¹ | `57ed002f-c6b3-433c-98a7-a6a017ae701f` | Erlangen | no |
| Filmforum im Museum Ludwig ¹ | `610f2aaf-b904-4a9f-8d00-c4aed48a58fa` | Köln | no |
| Luru Kino ¹ | `6e096984-740d-4e93-88bb-4aedb2beba36` | Leipzig | yes |
| MAGAZIN-Filmkunsttheater ¹ | `f7419c19-ba55-4d32-8e93-853a63891515` | Hamburg | no |
| Schaubühne Lindenfels ¹ | `36b6faba-e948-49c2-91a5-5ef5eb2d40d9` | Leipzig | yes |

¹ No screenings in the 30 days after 2026-10-11 (seasonal open-air cinemas, festivals, or inactive venues).

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
