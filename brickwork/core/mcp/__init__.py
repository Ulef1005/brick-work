"""OpenAPI-driven MCP adapter: one tool call is one authenticated API v2 request (M.11e, issue #113).

Tools take numbers, never a Brick Work item id (decision 7): the contract marks an item-id path parameter `x-mcp-item: true` and the item
schema `x-mcp-item: key`; the tool exposes `provider`, `kind` and `no` (`key` inside a body) for them, and the adapter resolves the number
with `GET /lookup` before the call. Collection records (copy, stock line, wish, storage, ...) keep their ids, taken from list results."""
from functools import lru_cache
import json
import re
from urllib.parse import quote, unquote
from uuid import uuid4

import jsonschema
from mcp import types
from mcp.shared.exceptions import McpError
import yaml

from ..contract import contract_v2_path

PROVIDERS = ['bricklink', 'rebrickable']                # the providers a number can be looked up in (decision 3: bricklink by default)
ITEM_FIELDS = ('provider', 'kind', 'no')

@lru_cache(maxsize=1)
def contract():
    return yaml.safe_load(contract_v2_path().read_text())


def resolve(spec, value):
    if isinstance(value, dict):
        if '$ref' in value:
            target = spec
            for key in value['$ref'][2:].split('/'):
                target = target[key]
            return resolve(spec, target)
        return {k: resolve(spec, v) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(spec, v) for v in value]
    return value


class Adapter:
    def __init__(self, client, *, allow_write=False):
        self.client, self.allow_write = client, allow_write
        self.spec = contract()
        self.operations = {op['operationId']: (method.upper(), path, resolve(self.spec, op))
            for path, methods in self.spec['paths'].items()
            for method, op in methods.items() if isinstance(op, dict) and 'operationId' in op}
        self.tools = {op['x-mcp-tool']: (method, path, op)
            for method, path, op in self.operations.values() if 'x-mcp-tool' in op}

    def can_write(self):
        if not self.allow_write:
            return False
        status, result = self.client.request('GET', '/me')
        return status == 200 and bool({'write', 'admin'} & set(result['data']['scopes']))

    def item_parameter(self, op):
        """The path parameter of `op` that is a Brick Work item id (marked `x-mcp-item`), or None."""
        found = [p for p in op.get('parameters', []) if p['in'] == 'path' and p.get('x-mcp-item')]
        return found[0] if found else None

    def item_properties(self, key=False):
        """What a tool takes in place of an item id: the provider, the kind and the number (`key` in a body, as the API names it)."""
        kind = self.spec['components']['schemas']['Kind']
        return {'provider': {'type': 'string', 'enum': PROVIDERS, 'default': 'bricklink',
                             'description': 'The provider whose number this is (bricklink unless named).'},
                'kind': kind, 'key' if key else 'no': {'type': 'string', 'description': 'The item number in that provider.'}}

    def without_ids(self, schema):
        """`schema` with every item key (`x-mcp-item: key`) reduced to provider, kind and key: a tool never names an item by id."""
        if isinstance(schema, list):
            return [self.without_ids(s) for s in schema]
        if not isinstance(schema, dict):
            return schema
        if schema.get('x-mcp-item') == 'key' or any(isinstance(s, dict) and s.get('x-mcp-item') == 'key' for s in schema.get('allOf', [])):
            return {'type': 'object', 'properties': self.item_properties(key=True), 'required': ['kind', 'key'], 'additionalProperties': False,
                    'description': 'The item, by number: provider (bricklink unless named), kind and key.'}
        return {k: self.without_ids(v) for k, v in schema.items()}

    def schema(self, op):
        properties, required = {}, []
        item = self.item_parameter(op)
        for p in op.get('parameters', []):
            if p['in'] in ('path', 'query'):
                if p is item:
                    properties.update(self.item_properties())
                    required.extend(['kind', 'no'])
                elif item and p['name'] == 'provider':
                    continue                                    # the item's provider is also this query's (get_prices: the colour space)
                else:
                    properties[p['name']] = p['schema']
                    if p.get('required'):
                        required.append(p['name'])
            elif p['name'] == 'If-Match':
                properties['if_match'] = p['schema']
        body = op.get('requestBody', {}).get('content', {}).get('application/json', {}).get('schema')
        if body:
            body = self.without_ids(body)
            if op.get('x-mcp-tool', '').startswith('update_'):
                properties['fields'] = body
                required.append('fields')
            else:
                properties.update(body.get('properties', {}))
                required.extend(body.get('required', []))
        if op.get('x-mcp-tool'):
            # A supplied key survives retries across tool calls; otherwise generate one.
            if any(p['name'] == 'Idempotency-Key' for p in op.get('parameters', [])):
                properties['idempotency_key'] = {'type': 'string', 'pattern': '^[A-Za-z0-9-]{1,80}$'}
        return {'type': 'object', 'properties': properties, 'required': required, 'additionalProperties': False}

    def list_tools(self):
        writable = self.can_write()
        return [types.Tool(name=name, description=op['summary'] + ' Parameters: ' + ', '.join(self.schema(op)['properties']),
                inputSchema=self.schema(op), annotations=types.ToolAnnotations(readOnlyHint=method == 'GET', destructiveHint=method == 'DELETE'))
            for name, (method, path, op) in self.tools.items() if method == 'GET' or writable]

    def call_tool(self, name, arguments=None):
        if arguments is None:
            arguments = {}
        if name not in self.tools:
            raise ValueError('Unknown tool')
        method, path, op = self.tools[name]
        if method != 'GET' and not self.can_write():
            return self.result(403, {'code': 'forbidden', 'status': 403, 'detail': 'Write tools are disabled'})
        jsonschema.validate(arguments, self.schema(op))
        query, body, headers = {}, None, {}
        parameters = op.get('parameters', [])
        path_names = {p['name'] for p in parameters if p['in'] == 'path'}
        item = self.item_parameter(op)
        values = {key: arguments[key] for key in path_names if not item or key != item['name']}
        if item:
            # The number becomes the item's id here and nowhere else; the lookup's own refusal (404, 409 ambiguous) is the tool's.
            # A BrickLink link can be colour-scoped, so the operation's own colour (same provider space) takes part in the lookup.
            scoped = {'color': arguments['color']} if 'color' in arguments and any(p['in'] == 'query' and p['name'] == 'color' for p in parameters) else {}
            status, found = self.client.request('GET', '/lookup', query={'provider': arguments.get('provider', 'bricklink'),
                                                                        'kind': arguments['kind'], 'key': arguments['no'], **scoped})
            if status != 200:
                return self.result(status, found)
            values[item['name']] = found['data']['id']
        for key, value in values.items():
            path = path.replace('{' + key + '}', quote(str(value), safe=''))
        for p in parameters:
            if p['in'] == 'query' and p['name'] in arguments:
                value = arguments[p['name']]
                query[p['name']] = str(value).lower() if isinstance(value, bool) else value
        if 'requestBody' in op:
            excluded = path_names | set(query) | {'if_match', 'idempotency_key'} | (set(ITEM_FIELDS) if item else set())
            body = arguments.get('fields', {k: v for k, v in arguments.items() if k not in excluded})
        if method != 'GET':
            headers['Idempotency-Key'] = arguments.get('idempotency_key') or str(uuid4())
        if 'if_match' in arguments:
            headers['If-Match'] = arguments['if_match']
        return self.result(*self.client.request(method, path, query=query, body=body, headers=headers), write=method != 'GET')

    @staticmethod
    def result(status, value, write=False):
        # Preserve receipts and page cursors; scalar/single reads return API data. Neither client follows a redirect, so a 3xx
        # (a merged item's 307) is the tool's error with its problem body, never an empty success.
        if status < 300 and not write and isinstance(value, dict) and 'page' not in value:
            value = value.get('data', value)
        return types.CallToolResult(content=[types.TextContent(type='text', text=json.dumps(value))],
            structuredContent=value if isinstance(value, dict) else None, isError=status >= 300)

    def read_resource(self, uri):
        for template, target in self.spec['x-mcp']['resources'].items():
            operation, query = (target, {}) if isinstance(target, str) else (target['operation'], target.get('query', {}))
            names = re.findall(r'\{([^}]+)\}', template)
            pattern = re.escape(template)
            for name in names:
                pattern = pattern.replace(re.escape('{' + name + '}'), '([^/]+)')
            match = re.fullmatch(pattern, uri)
            if match:
                method, path, _ = self.operations[operation]
                found = dict(zip(names, match.groups()))
                for name, value in found.items():
                    path = path.replace('{' + name + '}', quote(value, safe=''))
                # A query value is a template over the URI's variables: `{no}` is the number the lookup calls `key`.
                params = {key: re.sub(r'\{([^}]+)\}', lambda m: unquote(found[m[1]]), text) for key, text in query.items()}
                status, value = self.client.request(method, path, query=params or None)
                if not 200 <= status < 300:
                    code = value.get('code', 'http_error') if isinstance(value, dict) else 'http_error'
                    raise McpError(types.ErrorData(code=types.INTERNAL_ERROR,
                                                  message=f'{code} (HTTP {status})'))
                return value if isinstance(value, str) else json.dumps(value)
        raise ValueError('Unknown resource')
