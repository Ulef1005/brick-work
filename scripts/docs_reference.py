"""The generated reference pages of the docs site's Developers tab (App Docs Standard, B1b of doc-standard-v1).

docs/developer/api-v2-reference.md and docs/developer/mcp-reference.md each hold one markdown-exec block that prints one of
the functions below while Zensical builds the site. Both read their source when the site is built and copy nothing from it:
the API reference reads docs/brickwork/openapi-v2.yaml, and the MCP tables read the adapter the MCP server itself uses. A
change to the contract or to the server is therefore on the site at the next build, with nothing to keep in step by hand.
The paths are from the repository root, whatever the build's working directory. scripts/build_site.py puts the root on
PYTHONPATH for the build; to preview the docs alone, run `PYTHONPATH=. zensical serve` from the root.
"""
import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / 'docs/brickwork/openapi-v2.yaml'
METHODS = ('get', 'post', 'put', 'patch', 'delete', 'head', 'options')


def folded(title, text, language='yaml'):
    """A collapsed block (pymdownx.details) that holds a code block, fenced longer than any backtick run in the text."""
    fence = '`' * max(3, 1 + max((len(run) for run in re.findall('`+', text)), default=0))
    body = '\n'.join('    ' + line if line else '' for line in f'{fence}{language}\n{text.rstrip()}\n{fence}'.splitlines())
    return f'??? reference "{title}"\n\n{body}\n'


def api_v2():
    """Every operation of the v2 contract: its method and path, its summary and, folded, its request and responses."""
    import yaml
    contract = yaml.safe_load(CONTRACT.read_text())
    chunks = []
    for path, operations in contract['paths'].items():
        for method, operation in operations.items():
            if method not in METHODS:
                continue
            # The path goes in backticks: attr_list would read a trailing {id} as an attribute list and drop it.
            chunks.append(f'## {method.upper()} `{path}`\n')
            if operation.get('summary'):   # escaped: a summary names placeholders such as <site>, which would pass as raw HTML
                chunks.append(html.escape(operation['summary'].strip(), quote=False) + '\n')
            chunks.append(folded('Request and responses', yaml.safe_dump(operation, sort_keys=False, allow_unicode=True)))
    chunks.append('## Shared schemas and authentication\n')
    chunks.append(folded('Components', yaml.safe_dump(contract.get('components', {}), sort_keys=False, allow_unicode=True)))
    return '\n'.join(chunks)


def mcp_tables():
    """Read tools, write tools and resources, from the adapter the server itself uses."""
    from brickwork.core.mcp import Adapter, contract
    adapter = Adapter(client=None)
    rows = {'GET': [], 'write': []}
    for name, (method, path, op) in sorted(adapter.tools.items()):
        arguments = ', '.join(f'`{a}`' for a in adapter.schema(op)['properties']) or 'none'
        line = f'| `{name}` | {html.escape(op.get("summary", "")).capitalize()} | {arguments} | `{method} /api/v2{path}` |'
        rows['GET' if method == 'GET' else 'write'].append(line)
    head = '| Tool | What it does | Arguments | API call |\n|---|---|---|---|'
    resources = contract().get('x-mcp', {}).get('resources', {})
    resource_rows = '\n'.join(f'| `{uri}` | `{target if isinstance(target, str) else target["operation"]}` |' for uri, target in resources.items())
    text = (f'\n## Read tools ({len(rows["GET"])})\n\n{head}\n' + '\n'.join(rows['GET']) +
            f'\n\n## Write tools ({len(rows["write"])}, only with a write token and `--allow-write`)\n\n{head}\n' + '\n'.join(rows['write']))
    if resource_rows:
        text += f'\n\n## Resources ({len(resources)})\n\n| URI | API operation |\n|---|---|\n{resource_rows}'
    return text + '\n'
