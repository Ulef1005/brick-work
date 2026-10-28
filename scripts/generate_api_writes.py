"""Generate the request metadata of the write operations from the OpenAPI contracts: v1's (`brickwork/api/write_contract.json`, implemented M3, M4
and M6 operations) and v2's (`brickwork/api2/write_contract.json`, the operations of the pieces in `V2_PIECES`).

The generated files are the write transports' only knowledge of the contract: which operations exist, whether they take If-Match, whether the
Idempotency-Key is required, the request schema (with every schema it references) and what the answer may leave null."""
import json
from pathlib import Path
import sys
from scripts.check_api_contract import load_yaml

ROOT = Path(__file__).resolve().parents[1]
# M5 photo uploads share the multipart write path; the rest of M5 has its own transport.
PHOTOS = {'post_copies_id_photos', 'post_stock_id_photos'}
V2_PIECES = ('M.11c',)                                   # the pieces of API v2 whose write operations the transport serves; M.11d adds itself


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


def generated():
    c = load_yaml((ROOT/'docs/brickwork/openapi-v1.yaml').read_text())
    operations=[]
    for path,methods in c['paths'].items():
        for method,op in methods.items():
            if not isinstance(op,dict) or not (op.get('x-milestone') in ('M3','M4','M6') or op.get('operationId') in PHOTOS):continue
            if method=='get': continue
            resource=path.split('/')[1]
            action=('booklets' if path=='/stock/booklets' else path.rsplit('/',1)[-1] if path.count('/')>2 else {'post':'create','patch':'patch','delete':'archive'}[method])
            if path=='/orders/documents': action='documents'
            if path.endswith('/parts/{part_id}'): action='part'
            elif '/figures/{type}/{no}' in path: action='figure'
            if action=='booklets':resource='booklets';action='create'
            if resource=='found':action='create'
            content=op.get('requestBody',{}).get('content',{})
            media=next(iter(content),None)
            response=op['responses'].get('201',op['responses'].get('200'))
            ref=response['content']['application/json']['schema']['$ref'].split('/')[-1]
            operations.append(dict(path=path,method=method.upper(),endpoint=op['operationId'],resource=resource,action=action,
                if_match=any(p.get('$ref')=='#/components/parameters/IfMatch' for p in op.get('parameters',[])),
                schema=content.get(media,{}).get('schema'),multipart=media=='multipart/form-data',shape=ref.removeprefix('Written'),
                required=any(p.get('$ref')=='#/components/parameters/IdempotencyKeyRequired' for p in op.get('parameters',[]))))
    schemas=collect(c,operations)
    return json.dumps(dict(operations=operations,schemas=schemas),indent=2,sort_keys=True)+'\n'


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


TARGETS = ((ROOT/'brickwork/api/write_contract.json', generated), (ROOT/'brickwork/api2/write_contract.json', generated_v2))


if __name__=='__main__':
    for target, make in TARGETS:
        text = make()
        if '--write' in sys.argv:target.write_text(text)
        elif not target.exists() or target.read_text()!=text:raise SystemExit(f'Run python -m scripts.generate_api_writes --write ({target.relative_to(ROOT)} differs)')
