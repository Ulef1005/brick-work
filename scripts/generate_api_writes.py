"""Generate transport request metadata from implemented M3, M4 and M6 operations."""
import json
from pathlib import Path
import sys
from scripts.check_api_contract import load_yaml

ROOT = Path(__file__).resolve().parents[1]
# M5 photo uploads share the multipart write path; the rest of M5 has its own transport.
PHOTOS = {'post_copies_id_photos', 'post_stock_id_photos'}


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
    schemas={}
    def include(value):
        if isinstance(value,dict):
            if '$ref' in value:
                name=value['$ref'].split('/')[-1]
                if name not in schemas:
                    schemas[name]=c['components']['schemas'][name]
                    include(schemas[name])
            for v in value.values():include(v)
        elif isinstance(value,list):
            for v in value:include(v)
    for op in operations:include(op['schema'])
    return json.dumps(dict(operations=operations,schemas=schemas),indent=2,sort_keys=True)+'\n'


if __name__=='__main__':
    target=ROOT/'brickwork/api/write_contract.json'
    text=generated()
    if '--write' in sys.argv:target.write_text(text)
    elif not target.exists() or target.read_text()!=text:raise SystemExit('Run python -m scripts.generate_api_writes --write')
