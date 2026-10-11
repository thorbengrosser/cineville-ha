"""Constants for the Cineville integration."""

DOMAIN = "cineville"

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
