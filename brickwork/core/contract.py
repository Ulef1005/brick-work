"""Location and deployment diagnostics for the shared OpenAPI contract."""
from pathlib import Path

from .errors import InternalError

CONTRACT = Path(__file__).resolve().parents[2] / 'docs/brickwork/openapi-v1.yaml'


def contract_path():
    if not CONTRACT.is_file():
        raise InternalError(
            'OpenAPI contract is missing: docs/brickwork/openapi-v1.yaml. '
            'Rebuild the image with the contract included.')
    return CONTRACT


CONTRACT_V2 = Path(__file__).resolve().parents[2] / 'docs/brickwork/openapi-v2.yaml'


def contract_v2_path():
    """The API v2 contract (M.11a, issue #113); the v2 blueprint serves it and checks its own routes against it."""
    if not CONTRACT_V2.is_file():
        raise InternalError(
            'OpenAPI contract is missing: docs/brickwork/openapi-v2.yaml. '
            'Rebuild the image with the contract included.')
    return CONTRACT_V2
