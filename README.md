# cineville-ha

Home Assistant integration for [Cineville](https://cineville.de): today's showtimes in your cinemas,
plus your watchlist and the films you've seen.

Work in progress (no login, watchlist or ratings yet).

## The card

The integration ships its own dashboard card and loads it automatically; you don't need to add a resource.
Add it via *Add card → Cineville*, or in YAML:

```yaml
type: custom:cineville-card
view: films        # films (grouped by film) or list (chronological); switchable on the card
days: 7            # days in the day picker (1–8)
show_past: false   # today: also show screenings that have already started
# max_height: 500px  # for dashboards without a grid; in sections dashboards just resize the card
# title: Kino heute
# config_entry_id: ...   # only if you set up several cities
```

To work on the card without Home Assistant: `python3 -m http.server 8765` in the repo root, then open
<http://localhost:8765/dev/preview.html>. It renders the real card with a recorded Hamburg program (`dev/fixtures/`).

## Repository

So far:

- [`docs/api/`](docs/api/README.md): reverse-engineered documentation of the Cineville API, including the
  login flow ([authentication.md](docs/api/authentication.md))
- [`tools/cineville_login_test.py`](tools/cineville_login_test.py): end-to-end check of the login flow
- [`cinevillepreview.php`](cinevillepreview.php): the original PHP page this project grew out of
  (live at thorben.io/cineville/cinevillepreview.php)
