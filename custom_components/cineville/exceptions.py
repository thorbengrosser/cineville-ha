"""Exceptions raised by the Cineville client."""


class CinevilleError(Exception):
    """Base error."""


class CinevilleConnectionError(CinevilleError):
    """Network problem or unexpected server error; worth retrying later."""


class CinevilleAuthError(CinevilleError):
    """Login missing, expired or rejected; the user has to log in again."""
