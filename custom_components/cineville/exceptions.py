"""Exceptions raised by the Cineville client."""


class CinevilleError(Exception):
    """Base error."""


class CinevilleConnectionError(CinevilleError):
    """Network problem or unexpected server error; worth retrying later."""


class CinevilleAuthError(CinevilleError):
    """Login missing, expired or rejected; the user has to log in again."""


class CinevilleOtpError(CinevilleAuthError):
    """The emailed one-time code was wrong or has expired; the user can try again."""


class CinevilleLoginPageError(CinevilleError):
    """Cineville's login pages look different than expected; fall back to the manual login."""
