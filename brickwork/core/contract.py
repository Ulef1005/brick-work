"""Location and deployment diagnostics for the OpenAPI contract (API v2; the v1 contract file is a reference only, M.11e, issue #113)."""
from pathlib import Path

from .errors import InternalError

CONTRACT_V2 = Path(__file__).resolve().parents[2] / 'docs/brickwork/openapi-v2.yaml'


def contract_v2_path():
    """The API v2 contract (M.11a, issue #113); the v2 blueprint serves it and checks its own routes against it, and the MCP adapter reads its tools from it (M.11e)."""
    if not CONTRACT_V2.is_file():
        raise InternalError(
            'OpenAPI contract is missing: docs/brickwork/openapi-v2.yaml. '
            'Rebuild the image with the contract included.')
    return CONTRACT_V2
