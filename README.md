# cineville-ha

Home Assistant integration for [Cineville](https://cineville.de): today's showtimes in your cinemas,
plus your watchlist and the films you've seen.

Work in progress. So far:

- [`docs/api/`](docs/api/README.md): reverse-engineered documentation of the Cineville API, including the
  login flow ([authentication.md](docs/api/authentication.md))
- [`tools/cineville_login_test.py`](tools/cineville_login_test.py): end-to-end check of the login flow
- [`cinevillepreview.php`](cinevillepreview.php): the original PHP page this project grew out of
  (live at thorben.io/cineville/cinevillepreview.php)
