"""Write transport with a generated subset of the authoritative OpenAPI contract."""
import hashlib
import json
from pathlib import Path
import re

from flask import g, jsonify, request
from . import api, database
from .serializers import public
from ..core import api_writes as service, errors

SPEC = json.loads(Path(__file__).with_name('write_contract.json').read_text())


def validate(value, schema):
    if '$ref' in schema: return validate(value,SPEC['schemas'][schema['$ref'].split('/')[-1]])
    types = schema.get('type',[])
    if isinstance(types,str): types=[types]
    kind = 'null' if value is None else 'boolean' if type(value) is bool else 'integer' if type(value) is int else 'number' if type(value) is float else 'object' if isinstance(value,dict) else 'array' if isinstance(value,list) else 'string' if isinstance(value,str) else ''
    if types and kind not in types or 'enum' in schema and value not in schema['enum']:
        raise errors.ValidationFailed('Invalid field value')
    if isinstance(value,(str,list,dict)) and len(value)<schema.get('minItems',schema.get('minProperties',0)):
        raise errors.ValidationFailed('Supply at least one value')
    if isinstance(value,list) and len(value)>schema.get('maxItems',len(value)):
        raise errors.ValidationFailed('Too many values')
    if type(value) in (int,float) and value<schema.get('minimum',value):
        raise errors.ValidationFailed('Count must be zero or more')
    if isinstance(value,dict) and 'properties' not in schema and isinstance(schema.get('additionalProperties'),dict):
        for k,v in value.items():
            if 'propertyNames' in schema: validate(k,schema['propertyNames'])
            validate(v,schema['additionalProperties'])
    if isinstance(value,dict) and 'properties' in schema:
        fields = schema.get('properties',{})
        if set(value)-set(fields) or set(schema.get('required',[]))-set(value): raise errors.ValidationFailed('Unknown or missing field')
        for k,v in value.items(): validate(v,fields[k])
    elif isinstance(value,list):
        for v in value: validate(v,schema.get('items',{}))
    elif isinstance(value,str) and 'pattern' in schema:
        if not re.fullmatch(schema['pattern'],value): raise errors.ValidationFailed('Invalid field value')


def install():
    for op in SPEC['operations']:
        def handler(op=op, **values):
            allowed={'move_to_unstored'} if op['resource']=='storages' and op['action']=='archive' else set()
            if set(request.args)-allowed or any(len(request.args.getlist(k))!=1 for k in request.args): raise errors.UnknownFilter()
            content = None
            if op.get('multipart'):
                if request.mimetype != 'multipart/form-data': raise errors.UnsupportedMediaType()
                photo = op['action']=='photos'
                limit = (15 if photo else 20)*1024*1024
                file = request.files.get('file')
                if file is None: raise errors.ValidationFailed('Choose a photo' if photo else 'Choose a PDF')
                if photo and not (file.mimetype or '').startswith('image/'): raise errors.UnsupportedMediaType()
                content = file.read(limit+1)
                if len(content)>limit: raise errors.PayloadTooLarge()
                data = dict(request.form,file='upload')
                validate(data,op['schema'])
                data.pop('file')
                hashed = dict(data,file_sha256=hashlib.sha256(content).hexdigest())
            elif op.get('schema'):
                if request.mimetype != 'application/json': raise errors.UnsupportedMediaType()
                data = request.get_json(silent=True)
                if not isinstance(data,dict): raise errors.BadRequest('Expected a JSON object')
                validate(data,op['schema'])
                hashed = data
            else:
                if request.get_data(): raise errors.BadRequest('This action accepts no body')
                data = hashed = {}
                if allowed and 'move_to_unstored' in request.args:
                    value=request.args['move_to_unstored']
                    if value not in ('true','false'): raise errors.UnknownFilter()
                    data=hashed={'move_to_unstored':value=='true'}
            expected = request.if_match
            expect = None if not op['if_match'] or 'If-Match' not in request.headers else (['*'] if expected.star_tag else list(expected))
            def action():
                result,status = service.mutate(database(),op['resource'],values.get('id'),op['action'],data,expect,content,values=values)
                return result,status
            runner = service.execute
            if op['resource']=='orders' and op['action']=='documents' and data['source']=='api':
                from ..core import orders, api_orders
                def action():
                    if not re.fullmatch(r'[0-9]{1,12}', data.get('number','')):
                        raise errors.ValidationFailed('Use a BrickLink order number')
                    prepared=orders.api_data(database(),data['number'])
                    return lambda: api_orders.mutate(database(),None,'documents',data,values,prepared=prepared)
                runner=service.detached
            result,status = runner(database(),method=request.method,path=request.path,body=hashed,
                key=request.headers.get('Idempotency-Key'),required=op['required'],token_name=g.api_identity['name'],
                action=action,serialize=lambda data: public(data,op['shape']))
            return jsonify(result),status
        route = re.sub(r'\{(\w+)\}', lambda m: '<int:'+m[1]+'>' if m[1] in ('part_id','line_id','doc_id') or m[1]=='id' and op['resource'] in ('wishes','instruction-files','orders') else '<'+m[1]+'>', op['path'])
        api.add_url_rule(route,op['endpoint'],handler,methods=[op['method']])


install()
