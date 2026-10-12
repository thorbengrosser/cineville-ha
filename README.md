# Cineville for Home Assistant

Cineville is the most fun money can buy in any major German city. Their team is amazing, their offer is great, and even their website and app are pretty good. But what if you are a nerd and put dashboards everywhere in your house?

Cineville for HAss shows the [Cineville](https://cineville.de) Germany programme of your city on your Home Assistant dashboard: what's on today
(and the next days) in your cinemas, with posters, IMDb and Rotten Tomatoes ratings, and, if you log in, your
watchlist highlighted and the films you've already seen dimmed.

> **Unofficial.** This is not made or endorsed by Cineville. It uses the same API as the Cineville website and app,
> which is undocumented and can change without notice. See [docs/api](docs/api/README.md).

## What you get

- **A dashboard card**: grouped by film or as a chronological list, with a day picker, cinema and start-time filters,
  ticket links, and a "watchlist only" toggle. Times and dates follow your Home Assistant profile (language,
  12/24-hour time, time zone, date format).
- **Sensors**: *Upcoming screenings today*, *Next screening* (a timestamp with film, cinema and ticket link as
  attributes) and, when logged in, *Watchlist films today*, e.g. for a notification when a film from your watchlist
  is showing tonight.
- **An action**, `cineville.get_program`, that returns a whole day's program (used by the card, also handy in scripts).

Cineville currently covers 15 German cities (Berlin, Hamburg, Köln, …).

## Installation

1. In HACS: *⋮ → Custom repositories*, add `https://github.com/thorbengrosser/cineville-ha` as an **Integration**.
2. Search for **Cineville** in HACS, download it and restart Home Assistant.
3. *Settings → Devices & services → Add integration → Cineville*: pick your city and the cinemas you care about.
   If you keep all cinemas selected, cinemas that join Cineville later are included automatically.
4. On a dashboard: *Add card → Cineville*. The card comes with the integration; you don't need to add a resource.

Requires Home Assistant 2025.8 or newer.

## Options

*Settings → Devices & services → Cineville → Configure* has three pages:

### Cinemas

Change which cinemas are included.

### Cineville account (optional)

Log in to see your watchlist and the films you've already seen. Cineville has no passwords: you get a login link, log
in with your email address and the code Cineville emails you, and then copy one more code from the (blank) page you
end up on into Home Assistant. The dialog walks you through it; it's easiest on a computer. After that, Home Assistant
keeps the login fresh by itself. If it ever expires, you'll get a "re-authentication required" notice; the program
keeps working in the meantime.

### Ratings (optional)

IMDb and Rotten Tomatoes badges need two free API keys:
[TMDB](https://www.themoviedb.org/settings/api) (to find the film, since Cineville only has German titles) and
[OMDb](https://www.omdbapi.com/apikey.aspx) (for the ratings). Ratings are cached (complete ones are re-checked weekly,
incomplete ones daily) and the integration stays well within OMDb's free 1,000 requests per day. IMDb ratings with
fewer than 100 votes are hidden. New German releases often have no rating yet; they simply show no badge.

## The card

Add it via *Add card → Cineville* (it has a visual editor) or in YAML:

```yaml
type: custom:cineville-card
view: films           # films (grouped by film) or list (chronological); switchable on the card
days: 7               # days in the day picker (1–8)
show_past: false      # today: also show screenings that have already started
watchlist: highlight  # highlight or only (also switchable on the card); needs the account login
seen: dim             # dim, hide or show: films you've already seen
# title: Kino heute
# max_height: 500px     # for dashboards without a grid; in sections dashboards just resize the card
# config_entry_id: ...  # only if you set up several cities
```

The view and the "watchlist only" toggle are remembered per browser.

## The `cineville.get_program` action

```yaml
action: cineville.get_program
data:
  date: "2026-10-13"   # optional: today (default) up to 7 days ahead
  # config_entry_id: … # only if you set up several cities
response_variable: program
```

Returns `{day, today, city, timezone, logged_in, showtimes: [...]}`. Each showtime has `start`, `end`, `venue`,
`language_label` (OV/OmU/OmeU/DF), `specials`, `ticketing_url` and a `film` with title, poster, director, duration,
`on_watchlist`, `seen` and `ratings`. A Cineville day runs from 04:00 to 04:00, like on cineville.de.

## Troubleshooting

- **The card doesn't appear in the card picker**: reload the browser once after installing or updating.
- **No program / "could not load"**: check *Settings → System → Logs* for `cineville`. If Cineville changed their
  API, the weekly API check in this repository's GitHub Actions will usually have spotted it too.
- **Login code not accepted**: codes are valid for about 5 minutes and only work with the link shown in the same dialog.

## Development

- Tests: `python3 -m venv .venv && .venv/bin/pip install -r requirements_test.txt && .venv/bin/python -m pytest`
- Card preview without Home Assistant: `python3 -m http.server 8765` in the repo root, then open
  <http://localhost:8765/dev/preview.html>. It renders the real card with a recorded Hamburg program and real ratings
  (`dev/fixtures/`); URL parameters switch theme, language, size, login state and time format.
- [`docs/design.md`](docs/design.md): design decisions and milestones.
- [`docs/api/`](docs/api/README.md): reverse-engineered documentation of the Cineville API, including the login flow.
- [`tools/`](tools/): the login end-to-end check and the ratings matching spike.
- [`cinevillepreview.php`](cinevillepreview.php): the original PHP page this project grew out of.

## License

[MIT](LICENSE)
