"""OpenAPI-driven MCP adapter: one tool call is one authenticated API request."""
from functools import lru_cache
import json
import re
from urllib.parse import quote
from uuid import uuid4

import jsonschema
from mcp import types
from mcp.shared.exceptions import McpError
import yaml

from ..contract import CONTRACT, contract_path


@lru_cache(maxsize=1)
def contract():
    return yaml.safe_load(contract_path().read_text())


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

    @staticmethod
    def schema(op):
        properties, required = {}, []
        for p in op.get('parameters', []):
            if p['in'] in ('path', 'query'):
                properties[p['name']] = p['schema']
                if p.get('required'):
                    required.append(p['name'])
            elif p['name'] == 'If-Match':
                properties['if_match'] = p['schema']
        body = op.get('requestBody', {}).get('content', {}).get('application/json', {}).get('schema')
        if body:
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
        for key in path_names:
            path = path.replace('{' + key + '}', quote(str(arguments[key]), safe=''))
        for p in parameters:
            if p['in'] == 'query' and p['name'] in arguments:
                value = arguments[p['name']]
                query[p['name']] = str(value).lower() if isinstance(value, bool) else value
        if 'requestBody' in op:
            excluded = path_names | set(query) | {'if_match', 'idempotency_key'}
            body = arguments.get('fields', {k: v for k, v in arguments.items() if k not in excluded})
        if method != 'GET':
            headers['Idempotency-Key'] = arguments.get('idempotency_key') or str(uuid4())
        if 'if_match' in arguments:
            headers['If-Match'] = arguments['if_match']
        return self.result(*self.client.request(method, path, query=query, body=body, headers=headers), write=method != 'GET')

    @staticmethod
    def result(status, value, write=False):
        # Preserve receipts and page cursors; scalar/single reads return API data.
        if status < 400 and not write and isinstance(value, dict) and 'page' not in value:
            value = value.get('data', value)
        return types.CallToolResult(content=[types.TextContent(type='text', text=json.dumps(value))],
            structuredContent=value if isinstance(value, dict) else None, isError=status >= 400)

    def read_resource(self, uri):
        for template, operation in self.spec['x-mcp']['resources'].items():
            names = re.findall(r'\{([^}]+)\}', template)
            pattern = re.escape(template)
            for name in names:
                pattern = pattern.replace(re.escape('{' + name + '}'), '([^/]+)')
            match = re.fullmatch(pattern, uri)
            if match:
                method, path, _ = self.operations[operation]
                for name, value in zip(names, match.groups()):
                    path = path.replace('{' + name + '}', quote(value, safe=''))
                status, value = self.client.request(method, path)
                if not 200 <= status < 300:
                    code = value.get('code', 'http_error') if isinstance(value, dict) else 'http_error'
                    raise McpError(types.ErrorData(code=types.INTERNAL_ERROR,
                                                  message=f'{code} (HTTP {status})'))
                return value if isinstance(value, str) else json.dumps(value)
        raise ValueError('Unknown resource')
