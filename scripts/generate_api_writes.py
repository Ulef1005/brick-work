"""Generate the request metadata of the write operations of API v2 from its OpenAPI contract (`brickwork/api2/write_contract.json`, the operations of
the pieces in `V2_PIECES`; v1's file went with v1's write transport in M.11d).

The generated files are the write transports' only knowledge of the contract: which operations exist, whether they take If-Match, whether the
Idempotency-Key is required, the request schema (with every schema it references) and what the answer may leave null."""
import json
from pathlib import Path
import sys
from scripts.check_api_contract import load_yaml

ROOT = Path(__file__).resolve().parents[1]
V2_PIECES = ('M.11c', 'M.11d')                                   # the pieces of API v2 whose write operations the transport serves; M.11d added itself


def collect(c, operations):
    """`{name: schema}` of every component schema the request schemas of `operations` reach."""
    schemas = {}

    def include(value):
        if isinstance(value, dict):
            if '$ref' in value:
                name = value['$ref'].split('/')[-1]
                if name not in schemas:
                    schemas[name] = c['components']['schemas'][name]
                    include(schemas[name])
            for v in value.values():
                include(v)
        elif isinstance(value, list):
            for v in value:
                include(v)
    for op in operations:
        include(op['schema'])
    return schemas


def generated_v2():
    """The write operations of API v2 in the pieces of `V2_PIECES`, in contract order."""
    c = load_yaml((ROOT/'docs/brickwork/openapi-v2.yaml').read_text())
    shared = c['components']['parameters']
    operations = []
    for path, methods in c['paths'].items():
        for method, op in methods.items():
            if not isinstance(op, dict) or method == 'get' or op.get('x-piece') not in V2_PIECES:
                continue
            refs = [p['$ref'].rsplit('/', 1)[-1] for p in op.get('parameters', []) if '$ref' in p]
            declared = [shared[p['$ref'].rsplit('/', 1)[-1]] if '$ref' in p else p for p in op.get('parameters', [])]
            content = op.get('requestBody', {}).get('content', {})
            media = next(iter(content), None)
            statuses = sorted(int(s) for s in op['responses'] if s.isdigit() and s.startswith('2'))
            written = c['components']['schemas'][op['responses'][str(statuses[0])]['content']['application/json']['schema']['$ref'].rsplit('/', 1)[-1]]['properties']

            def nullable(name):
                kind = written.get(name, {}).get('type', [])
                return 'null' in (kind if isinstance(kind, list) else [kind])
            operations.append(dict(
                endpoint=op['operationId'], method=method.upper(), path=path, piece=op['x-piece'],
                if_match='IfMatch' in refs, required='IdempotencyKeyRequired' in refs,
                schema=content.get(media, {}).get('schema'), multipart=media == 'multipart/form-data',
                query=[p['name'] for p in declared if p.get('in') == 'query'], statuses=statuses,
                event_nullable=nullable('event_id'), undo_nullable=nullable('undo_url')))
    return json.dumps(dict(operations=operations, schemas=collect(c, operations)), indent=2, sort_keys=True) + '\n'


TARGETS = ((ROOT/'brickwork/api2/write_contract.json', generated_v2),)


if __name__=='__main__':
    for target, make in TARGETS:
        text = make()
        if '--write' in sys.argv:target.write_text(text)
        elif not target.exists() or target.read_text()!=text:raise SystemExit(f'Run python -m scripts.generate_api_writes --write ({target.relative_to(ROOT)} differs)')
