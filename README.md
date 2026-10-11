# cineville-ha

Home Assistant integration for [Cineville](https://cineville.de): today's showtimes in your cinemas,
plus your watchlist and the films you've seen.

Work in progress.

## IMDb and Rotten Tomatoes ratings (optional)

Under *Configure → Ratings*, enter two free API keys: [TMDB](https://www.themoviedb.org/settings/api) (to find the
film; Cineville only has German titles) and [OMDb](https://www.omdbapi.com/apikey.aspx) (for the ratings). The card
then shows IMDb (hidden below 100 votes) and Rotten Tomatoes badges. Ratings are cached: complete ones are re-checked
weekly, incomplete ones daily, and the integration stays well within OMDb's free 1,000 requests per day.
New German releases often have no IMDb or Rotten Tomatoes rating yet; those films simply show no badge.

## Watchlist and seen films (optional)

Log in under *Settings → Devices & services → Cineville → Configure → Cineville account*. Cineville has no passwords:
you log in with your email address and a code they send you, then copy one more code from the page you end up on
(the dialog explains how). After that, Home Assistant keeps the login fresh by itself; if it ever expires, you get a
"re-authentication required" notice.

When logged in, the card highlights films on your watchlist (or shows only those), dims films you've already seen,
and there's a *Watchlist films today* sensor for automations.

## The card

The integration ships its own dashboard card and loads it automatically; you don't need to add a resource.
Add it via *Add card → Cineville*, or in YAML:

```yaml
type: custom:cineville-card
view: films        # films (grouped by film) or list (chronological); switchable on the card
days: 7            # days in the day picker (1–8)
show_past: false   # today: also show screenings that have already started
# max_height: 500px  # for dashboards without a grid; in sections dashboards just resize the card
watchlist: highlight  # highlight or only (also switchable on the card); needs the account login
seen: dim             # dim, hide or show: films you've already seen
# title: Kino heute
# config_entry_id: ...   # only if you set up several cities
```

Times and dates follow your Home Assistant profile settings (language, 12/24-hour time, time zone, date format).

To work on the card without Home Assistant: `python3 -m http.server 8765` in the repo root, then open
<http://localhost:8765/dev/preview.html>. It renders the real card with a recorded Hamburg program (`dev/fixtures/`).

## Repository

So far:

- [`docs/api/`](docs/api/README.md): reverse-engineered documentation of the Cineville API, including the
  login flow ([authentication.md](docs/api/authentication.md))
- [`tools/cineville_login_test.py`](tools/cineville_login_test.py): end-to-end check of the login flow
- [`cinevillepreview.php`](cinevillepreview.php): the original PHP page this project grew out of
  (live at thorben.io/cineville/cinevillepreview.php)
