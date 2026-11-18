"""server.json for the MCP Registry names the image at the app's version, and the image carries the matching label (#477)."""

import json
from pathlib import Path

from brickwork.version import __version__

ROOT = Path(__file__).resolve().parent.parent
SERVER = json.loads((ROOT / "server.json").read_text())


def test_server_json_version_and_image_tag_equal_app_version():
    assert SERVER["version"] == __version__
    packages = SERVER["packages"]
    assert [p["identifier"] for p in packages] == [f"ghcr.io/ulef1005/brick-work:{__version__}"]


def test_server_json_runs_the_brickwork_command_over_stdio():
    (package,) = SERVER["packages"]
    assert package["registryType"] == "oci" and package["transport"] == {"type": "stdio"}
    runtime = {a["name"]: a for a in package["runtimeArguments"]}
    assert runtime["--entrypoint"]["value"] == "brickwork"
    assert [a.get("value") for a in package["packageArguments"] if a["type"] == "positional"] == ["mcp"]


def test_image_label_matches_the_server_name():
    label = f'LABEL io.modelcontextprotocol.server.name="{SERVER["name"]}"'
    assert label in (ROOT / "Dockerfile").read_text().splitlines()
