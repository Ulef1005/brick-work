"""Where the fetchers read their credentials (M.8 seam): the environment by default, an injected provider when the app has one.

A credential is named by its environment variable (`BW_BRICKLINK_CONSUMER_KEY`, `BW_REBRICKABLE_API_KEY`, ...). Without a
provider `get(name)` is `os.environ.get(name)`, exactly as before. With one, `set_key_provider(provider)` makes
`provider(name) -> str | None` the only source: the environment is not read, and None (or an empty string) means "not configured".
The provider is process-wide; `set_key_provider(None)` restores the environment. `store4` knows nothing of the app's own key
store: the app passes a callable."""
import os

_provider = None


def set_key_provider(provider):
    """Install `provider(name) -> str | None` (None removes it). Returns the previous provider so a caller can restore it."""
    global _provider
    if provider is not None and not callable(provider):
        raise TypeError('a key provider is a callable taking the credential name')
    previous, _provider = _provider, provider
    return previous


def get(name):
    """The value of credential `name`, or None when it is not configured."""
    value = os.environ.get(name) if _provider is None else _provider(name)
    return value or None
