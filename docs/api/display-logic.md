# Display logic (how cineville.de presents the data)

The API returns raw data; the website derives what you see on the page. To match the website,
copy these rules, which are taken from the `_app` bundle.

## Language label

Function `aT(country, languageVersion, subtitles)`. For country `DE`, first match wins:

| Condition | Label |
|---|---|
| `languageVersion == "original"` and no subtitles | `OV` |
| `languageVersion == "original"` and any subtitle contains `"en"` | `OmeU` |
| `languageVersion == "original"` and other subtitles | `OmU` |
| `languageVersion` contains `"de"` (e.g. `"de-DE"`) | `DF` (dubbed German) |
| anything else (null, `{}`, `"en-GB"`, `"fa"`) | *no label* |

(The Belgian site uses `VO`/`VF`/`VN` with "st FR/NL" etc. Not relevant here.)

## End time

If `endDate` is null, the website computes:

```
end = floor_to_5_minutes(startDate + duration_minutes + 15)
```

The `+15` minutes is for ads and trailers. If `duration` is missing too, there is no end time.

## "Today" and the day boundary

The site's day filter runs from **04:00 local time to 04:00 the next day** (`Europe/Berlin`).
The "ab jetzt" (from now) option has the internal value `04:00`. For "today" the website sends:

- `startDate.gte` = now (or the chosen hour, e.g. `21:00` local)
- `startDate.lt`  = next day 04:00 local, as UTC

So a 01:30 late show counts as "today". (Our old PHP cut off at 02:00.)

## Specials line

`attributes.tags` are translated, then `localizableAttributes.customTags` are appended, joined with
`", "`, and the first letter is capitalised. German (`de-DE`) translations:

| tag | label |
|---|---|
| `preview` | Preview |
| `sneakPreview` | Sneak Preview |
| `classic` | Klassiker |
| `modernClassic` | Moderner Klassiker |
| `3d` | 3D |
| `70mm` | 70-mm |
| `englishSubs` | OmeU |
| `special` | Special |
| `outdoorCinema` | Freiluftkino *(in the translations, not in the API enum)* |

## Highlights (film badges)

From `production.attributes.highlights[]`. A highlight is **active** when today is within
`[startDate, endDate]` (both optional). The first active one in the order
`filmOfTheWeek`, `tip`, `upcomingFilm`, `freshTrailer` becomes the film's badge (`defaultHighlight`):

| type | de-DE label |
|---|---|
| `filmOfTheWeek` | Film der Woche |
| `tip` | Tipp von {author} (default author "Cineville") |
| `freshTrailer` | Frischer Trailer |
| `upcomingFilm` | Demnächst |

The explanatory text is in `localizableAttributes.highlightDescriptions.<type>`.

## Mapped showtime object

For reference, this is the flattened object the website builds per event (`aO()`). The old GraphQL API
returned exactly this shape, so it's a good target shape for our own client:

```
{ id, startDate, endDate (computed fallback), subtitles, languageVersion, languageVersionAbbreviation,
  specials, ticketingUrl,
  film:    { id, slug, title, cover, poster, trailer, cast, duration, directors, releaseYear,
             spokenLanguages, premiereDate, contentRatingMinimumAge, highlights, defaultHighlight,
             description, shortDescription, editorsNote },
  theater: { id, slug, name, address, cover, website, shortDescription, intro, description, ticketInfo } }
```
