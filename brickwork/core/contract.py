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
