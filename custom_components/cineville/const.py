"""Constants for the Cineville integration."""

from datetime import timedelta

DOMAIN = "cineville"

# Config entry keys. venue_ids == [] means "the whole city" (new cinemas are picked up automatically).
CONF_CITY_ID = "city_id"
CONF_CITY_NAME = "city_name"
CONF_VENUE_IDS = "venue_ids"

# Logged-in Cineville accounts: entry.data[CONF_ACCOUNTS] = [{user_id, account_name, tokens}, ...]
# (see accounts.py; config entry version 1 stored a single account directly in entry.data)
CONF_ACCOUNTS = "accounts"
CONF_TOKENS = "tokens"
CONF_EMAIL = "email"
CONF_USER_ID = "user_id"
CONF_ACCOUNT_NAME = "account_name"
# Ratings API keys in entry.data (set by the "Ratings" options step)
CONF_TMDB_KEY = "tmdb_api_key"
CONF_OMDB_KEY = "omdb_api_key"
# How long get_program waits for missing ratings before answering (the rest arrive on the next call)
RATINGS_WAIT_SECONDS = 8

UPDATE_INTERVAL = timedelta(minutes=30)
ACCOUNT_UPDATE_INTERVAL = timedelta(minutes=60)
# Other days requested by the card are cached this long
DAY_CACHE_TTL = timedelta(minutes=30)
# The day picker can look this many days ahead (Cineville publishes about a week)
MAX_DAYS_AHEAD = 7

SERVICE_GET_PROGRAM = "get_program"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_DATE = "date"

API_URL = "https://api.cineville.de"
WEBSITE_URL = "https://cineville.de"
TENANT_ID = "cineville.de"
DEFAULT_LOCALE = "de-DE"
DEFAULT_TIMEZONE = "Europe/Berlin"
# A Cineville "day" runs from 04:00 to 04:00 local time (tenant scheduleWeek.startHour)
DEFAULT_DAY_START_HOUR = 4

# Mobile app OAuth client (public, PKCE). Also published as appAuthClientId in /api/tenants.
APP_CLIENT_ID = "0d6499ff-c493-4647-8ea3-72cf7543c369"
REDIRECT_URI = "cineville://login-callback"
OAUTH_SCOPE = "openid api offline_access profile email"

# Server-side maximum for page.limit
MAX_PAGE_LIMIT = 1000
# Safety net when following _links.next
MAX_PAGES = 20

# If endDate is missing, cineville.de estimates it as start + duration + 15 min, rounded down to 5 min
END_TIME_PADDING_MINUTES = 15

# Event tags (production-types/film eventAttributesSchema) and their German labels on cineville.de
SPECIAL_LABELS_DE = {
    "preview": "Preview",
    "sneakPreview": "Sneak Preview",
    "classic": "Klassiker",
    "modernClassic": "Moderner Klassiker",
    "3d": "3D",
    "70mm": "70-mm",
    "englishSubs": "OmeU",
    "special": "Special",
    "outdoorCinema": "Freiluftkino",
}

# Order in which cineville.de picks a film's badge from its active highlights
HIGHLIGHT_PRIORITY = ("filmOfTheWeek", "tip", "upcomingFilm", "freshTrailer")
