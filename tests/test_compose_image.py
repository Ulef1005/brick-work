"""compose.yaml names the published image at the app's own version (#78)."""

from pathlib import Path

from brickwork.version import __version__

COMPOSE = Path(__file__).resolve().parent.parent / "compose.yaml"


def test_compose_image_tag_equals_app_version():
    lines = [ln.strip() for ln in COMPOSE.read_text().splitlines()]
    images = [ln for ln in lines if ln.startswith("image:")]
    assert images == [f"image: ghcr.io/ulef1005/brick-work:{__version__}"]
