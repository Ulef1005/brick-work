"""The demo's own "now": one fixed instant, for the screen gate's world and for the exported demo.

Price quotes count as stale after seven days and pages show dates relative to the clock, so a demo built on any other day would
look different, and an old one would turn every price stale. `freeze_clock` makes every brickwork module that imported `datetime`
see FIXED_NOW (the demo dataset's own "now"); `thaw_clock` puts the real clock back (the gate also runs inside the test suite's process).
"""
import datetime as dt
import sys

FIXED_NOW = dt.datetime(2026, 10, 12, 8, 0, 0, tzinfo=dt.timezone.utc)


class FrozenDatetime(dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return FIXED_NOW.astimezone(tz) if tz else FIXED_NOW.replace(tzinfo=None)

    @classmethod
    def utcnow(cls):
        return FIXED_NOW.replace(tzinfo=None)


def freeze_clock() -> list:
    """The app's clock stands at FIXED_NOW: every brickwork module that imported `datetime` gets the frozen class. Returns the modules
    patched, for `thaw_clock`."""
    import brickwork  # noqa: F401
    patched = []
    for name, module in list(sys.modules.items()):
        if name.startswith('brickwork') and getattr(module, 'datetime', None) is dt.datetime:
            module.datetime = FrozenDatetime
            patched.append(module)
    return patched


def thaw_clock(patched: list) -> None:
    for module in patched:
        module.datetime = dt.datetime
