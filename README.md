<p align="center">
  <img src="https://raw.githubusercontent.com/thorbengrosser/cineville-ha/main/custom_components/cineville/brand/icon@2x.png" width="112" alt="Cineville for Home Assistant icon">
</p>

<h1 align="center">Cineville for Home Assistant</h1>

<p align="center">
  Show the upcoming programme for your Cineville movie pass, right on your Home Assistant dashboard.
</p>

<p align="center">
  <a href="https://hacs.xyz/docs/faq/custom_repositories"><img src="https://img.shields.io/badge/HACS-Custom-41BDF5.svg" alt="HACS Custom"></a>
  <a href="https://github.com/thorbengrosser/cineville-ha/releases"><img src="https://img.shields.io/github/v/release/thorbengrosser/cineville-ha?label=release" alt="Latest release"></a>
  <a href="https://github.com/thorbengrosser/cineville-ha/actions/workflows/validate.yml"><img src="https://github.com/thorbengrosser/cineville-ha/actions/workflows/validate.yml/badge.svg" alt="Validate"></a>
  <img src="https://img.shields.io/badge/Home%20Assistant-2025.8%2B-18BCF2?logo=homeassistant&logoColor=white" alt="Home Assistant 2025.8+">
  <a href="LICENSE"><img src="https://img.shields.io/github/license/thorbengrosser/cineville-ha" alt="License: MIT"></a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/thorbengrosser/cineville-ha/main/docs/images/card-films-light.png" width="32%" alt="The card grouped by film: posters, ratings, watchlist markers and showtimes">
  <img src="https://raw.githubusercontent.com/thorbengrosser/cineville-ha/main/docs/images/card-list-dark.png" width="32%" alt="The card as a chronological list in dark mode">
  <img src="https://raw.githubusercontent.com/thorbengrosser/cineville-ha/main/docs/images/card-watchlist-compact-dark.png" width="32%" alt="Combined watchlists of two people, with an already seen film compacted to one line">
</p>

Cineville is the most fun money can buy in any major German city. Their team is amazing, their offer is great, and even their website and app are pretty good. But what if you are a nerd and put dashboards everywhere in your house?

Cineville for HAss shows the [Cineville](https://cineville.de) Germany programme of your city on your Home Assistant dashboard: what's on today (and the next days) in your cinemas, with posters, IMDb and Rotten Tomatoes ratings, and, if you log in, your watchlist highlighted and the films you've already seen dimmed.

> [!NOTE]
> **Unofficial.** This project is not made or endorsed by Cineville. It uses the same API as the Cineville website and app, which is undocumented and can change without notice ([API notes](docs/api/README.md)).

## ✨ Features

- 🎬 **Dashboard card**: grouped by film or as a chronological list, day picker for the coming week, cinema and start-time filters, posters, OV/OmU/OmeU/DF labels, specials, ticket links. It fits any card size, follows your theme (light and dark), and speaks English and German.
- 🔖 **Your watchlist**: log in with your Cineville account to highlight watchlist films or show only those. Seen films can be dimmed, compacted to one line, or hidden.
- 👥 **Household and friends**: connect several accounts; coloured initials show whose watchlist a film is on. Choose who's in your household: films the whole household wants get a green stripe, a filter finds them, and a film only counts as seen once the whole household has seen it. Friends' wishes and seen films still show, with outlined initials.
- 🍅 **Ratings**: IMDb and Rotten Tomatoes badges (with free TMDB and OMDb API keys).
- 🤖 **Automations**: sensors for upcoming screenings, the next screening, and watchlist films showing today, plus a `cineville.get_program` action.
- 🔐 **Easy login**: enter your email in Home Assistant and type in the code Cineville emails you. No passwords, nothing to copy.

Cineville currently covers 15 German cities: Aachen, Berlin, Bonn, Braunschweig, Bremen, Düsseldorf, Freiburg, Fürth, Hamburg, Köln, Leverkusen, Nürnberg, Potsdam, Wuppertal and Würzburg.

## 📦 Installation

[![Open your Home Assistant instance and open this repository inside HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=thorbengrosser&repository=cineville-ha&category=integration)

Or manually in HACS:

1. *HACS → ⋮ → Custom repositories*, add `https://github.com/thorbengrosser/cineville-ha` with type **Integration**.
2. Search for **Cineville**, download it, and restart Home Assistant.

Requires Home Assistant **2025.8** or newer.

## ⚙️ Setup

[![Open your Home Assistant instance and start setting up Cineville.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=cineville)

1. *Settings → Devices & services → Add integration → Cineville*.
2. Pick your city, then the cinemas you care about. If you keep all of them selected, cinemas that join Cineville later are included automatically.
3. On a dashboard: *Add card → Cineville*. The card ships with the integration; there's no resource to add.

Afterwards, *Configure* on the integration has three pages:

| Page | What it does |
|---|---|
| **Cinemas** | Change which cinemas are included. |
| **Cineville account** | *Add an account*: enter your email address, then the code Cineville emails you. Add as many people as you like; their watchlists are combined on the card. *Choose the household* decides who counts for "seen by everyone" and the green "whole household" stripe; everyone else counts as a friend. *Add an account manually* is a fallback in case Cineville changes their login pages. *Remove an account* logs out. If a login ever expires, Home Assistant asks you to renew it; the programme keeps working meanwhile. |
| **Ratings** | Two free API keys: [TMDB](https://www.themoviedb.org/settings/api) finds the film (Cineville only has German titles) and [OMDb](https://www.omdbapi.com/apikey.aspx) provides the ratings. Ratings are cached and the integration stays well within OMDb's free 1,000 requests per day. IMDb ratings with fewer than 100 votes are hidden; brand-new German releases often have no rating yet. |

## 🎬 The card

The card has a visual editor. In YAML:

```yaml
type: custom:cineville-card
view: films           # films or list; switchable on the card
days: 7               # days in the day picker (1–8)
seen: dim             # show, dim, compact or hide films that everyone has seen
watchlist: highlight  # highlight or only; switchable on the card
```

| Option | Default | Description |
|---|---|---|
| `view` | `films` | `films` (grouped by film, with poster and description) or `list` (one row per screening). |
| `days` | `7` | How many days the day picker offers (1–8). A Cineville day runs from 04:00 to 04:00, so a late show after midnight still belongs to "today". |
| `show_past` | `false` | Also show today's screenings that have already started. |
| `watchlist` | `highlight` | `highlight` watchlist films, or show `only` those. With several accounts, a dropdown picks anyone's, the whole household's or one person's watchlist. |
| `seen` | `dim` | Films the whole household has seen: `show`, `dim`, `compact` (one dimmed line with time and title) or `hide`. |
| `title` | `Cineville <city>` | Card title. |
| `max_height` | none | Maximum height, e.g. `500px`, for dashboards without a grid. In sections dashboards, just resize the card. |
| `config_entry_id` | none | Only needed if you set up several cities. |

The chosen view and watchlist filter are remembered per browser. Times and dates follow your Home Assistant profile settings.

## 🤖 Sensors and automations

| Entity | State | Attributes |
|---|---|---|
| `sensor.cineville_<city>_upcoming_screenings_today` | screenings still to come today | `films`, `screenings_total`, `day` |
| `sensor.cineville_<city>_next_screening` | start time of the next screening | `film`, `venue`, `language`, `specials`, `end`, `poster`, `ticketing_url` |
| `sensor.cineville_<city>_watchlist_films_today` | household watchlist films (not yet seen by the whole household) still showing today | `films`: title, start, venue, language, who wants to see it |

Get a notification when a film from your watchlist is on today:

```yaml
automation:
  - alias: "Cineville: watchlist film today"
    triggers:
      - trigger: numeric_state
        entity_id: sensor.cineville_hamburg_watchlist_films_today
        above: 0
    actions:
      - action: notify.mobile_app_your_phone
        data:
          title: "🎬 On your watchlist today"
          message: >-
            {% for f in state_attr('sensor.cineville_hamburg_watchlist_films_today', 'films') %}
            {{ f.title }}: {{ as_timestamp(f.start) | timestamp_custom('%H:%M') }} at {{ f.venue }}
            {% endfor %}
```

The `cineville.get_program` action returns a whole day's programme, for your own scripts and templates:

```yaml
action: cineville.get_program
data:
  date: "2026-10-13"   # optional: today (default) up to 7 days ahead
response_variable: program
```

<details>
<summary>What's in the response</summary>

`{day, today, city, timezone, logged_in, accounts, showtimes: [...]}`. `accounts` lists `{id, name, household}`. Each showtime has `start`, `end`, `venue`, `language_label` (OV/OmU/OmeU/DF), `specials`, `ticketing_url` and a `film` with title, poster, director, duration, `ratings`, `watchlist_by` / `seen_by` (account IDs), `on_watchlist` (on anyone's watchlist) and `seen` (seen by the whole household).

</details>

## 🛠 Troubleshooting

<details>
<summary>The card shows "Configuration error" or is missing from the card picker</summary>

Reload the browser once after installing or updating. If it persists, check that *Settings → Dashboards → ⋮ → Resources* lists `/cineville_static/cineville-card.js`; the integration adds it on startup.

</details>

<details>
<summary>No programme / "could not load the program"</summary>

Check *Settings → System → Logs* for `cineville`. If Cineville changed their API, the weekly API check in this repository's GitHub Actions has usually spotted it too; please open an issue.

</details>

<details>
<summary>The login code isn't accepted</summary>

The emailed code is valid for a few minutes; just try again. With *Add an account manually*, a code only works together with the link shown in the same dialog.

</details>

## 🧑‍💻 Development

- **Tests**: `python3 -m venv .venv && .venv/bin/pip install -r requirements_test.txt && .venv/bin/python -m pytest`
- **Card preview without Home Assistant**: run `python3 -m http.server 8765` in the repository and open <http://localhost:8765/dev/preview.html>. It renders the real card with a recorded Hamburg programme and real ratings; URL parameters switch theme, language, size, login state and more.
- **Screenshots**: `python3 tools/make_screenshots.py` regenerates the images above with headless Chrome.
- **Docs**: [design decisions](docs/design.md) and the [reverse-engineered Cineville API](docs/api/README.md), including the login flow.
- [`cinevillepreview.php`](cinevillepreview.php) is the original PHP page this project grew out of.

## 🙏 Credits

- Programme data: [Cineville](https://cineville.de), via its (unofficial) API.
- Ratings: [OMDb API](https://www.omdbapi.com/) (IMDb and Rotten Tomatoes ratings) and [TMDB](https://www.themoviedb.org/) (matching films). This product uses the TMDB API but is not endorsed or certified by TMDB.

## License

[MIT](LICENSE)
