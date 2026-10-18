"""Official SDK protocol hosts for stdio and Streamable HTTP."""
from contextlib import asynccontextmanager
from contextvars import ContextVar
import os
from pathlib import Path

import anyio
from mcp import types
from mcp.server import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.stdio import stdio_server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.middleware.wsgi import WSGIMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from . import Adapter, contract
from .client import HTTPClient, InProcessClient


def protocol(adapter):
    """The adapter supplier is request-local for HTTP and fixed for stdio."""
    server = Server('brickwork', version='1.0.0')

    @server.list_tools()
    async def list_tools():
        return await anyio.to_thread.run_sync(adapter().list_tools)

    @server.call_tool(validate_input=False)
    async def call_tool(name, arguments):
        # Adapter validates after checking the current caller's write gate; the SDK
        # tool cache is shared and is never an authorization source.
        return await anyio.to_thread.run_sync(lambda: adapter().call_tool(name, arguments))

    @server.list_resources()
    async def list_resources():
        return [types.Resource(uri=uri, name=uri, mimeType='application/yaml' if uri.endswith('openapi') else 'application/json')
            for uri in contract()['x-mcp']['resources'] if '{' not in uri]

    @server.list_resource_templates()
    async def list_resource_templates():
        return [types.ResourceTemplate(uriTemplate=uri, name=uri, mimeType='application/json')
            for uri in contract()['x-mcp']['resources'] if '{' in uri]

    @server.read_resource()
    async def read_resource(uri):
        content = await anyio.to_thread.run_sync(lambda: adapter().read_resource(str(uri)))
        return [ReadResourceContents(content, 'application/yaml' if str(uri).endswith('openapi') else 'application/json')]

    return server


async def serve_stdio(adapter):
    server = protocol(lambda: adapter)
    async with stdio_server() as (reader, writer):
        await server.run(reader, writer, server.create_initialization_options())


def http_app(flask_app, *, allow_write=False):
    """ASGI host: /mcp plus the same Flask application's WSGI routes."""
    current = ContextVar('brickwork_mcp_adapter')
    server = protocol(current.get)
    manager = StreamableHTTPSessionManager(server, stateless=True, json_response=True)

    async def endpoint(scope, receive, send):
        from starlette.requests import Request
        header = Request(scope).headers.get('authorization', '')
        token = header[7:] if header.startswith('Bearer ') else ''
        client = (scope.get('client') or (None,))[0]
        adapter = Adapter(InProcessClient(flask_app, token, remote_addr=client), allow_write=allow_write)
        status, identity = await anyio.to_thread.run_sync(lambda: adapter.client.request('GET', '/me'))
        if status != 200:
            response = JSONResponse(identity, status_code=status, media_type='application/problem+json',
                                    headers={'WWW-Authenticate': 'Bearer'})
            await response(scope, receive, send)
            return
        handle = current.set(adapter)
        try:
            await manager.handle_request(scope, receive, send)
        finally:
            current.reset(handle)

    @asynccontextmanager
    async def lifespan(app):
        async with manager.run():
            yield

    # Mount takes an ASGI callable; Route would treat a function as Request -> Response.
    class MCP:
        async def __call__(self, scope, receive, send):
            await endpoint(scope, receive, send)

    return Starlette(routes=[Route('/mcp', MCP(), methods=['GET', 'POST', 'DELETE']),
                             Mount('/', app=WSGIMiddleware(flask_app))], lifespan=lifespan)


def run(*, in_process=False, transport='stdio', api_url='http://127.0.0.1:5000/api/v1',
        token_file=None, allow_write=False, host='127.0.0.1', port=5000):
    # Validate before either transport starts accepting requests.
    contract()
    from flask import Flask
    from ...api import register
    from ... import settings
    from ...app import setup_app
    settings.load_env_file()
    allow_write = allow_write or os.environ.get('BW_MCP_WRITE') == '1'
    if transport == 'http':
        import uvicorn
        app = Flask('brickwork', template_folder='../templates', static_folder='../static')
        setup_app(app)
        if problem := settings.exposure_problem(app.config):
            raise SystemExit(problem)
        uvicorn.run(http_app(app, allow_write=allow_write), host=host, port=port)
        return
    token = Path(token_file).read_text().strip() if token_file else os.environ.get('BW_API_TOKEN', '')
    if in_process:
        app = Flask('brickwork-mcp')
        register(app)
        client = InProcessClient(app, token)
    else:
        client = HTTPClient(api_url, token)
    anyio.run(serve_stdio, Adapter(client, allow_write=allow_write))
