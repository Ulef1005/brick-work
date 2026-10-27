"""Check the implemented operation tables against OpenAPI (v1 and v2); --write refreshes them.

v2 (M.11a, issue #113): the contract `openapi-v2.yaml` against the routes of the `/api/v2` blueprint (every operation routed, exactly the
pieces in `brickwork.api2.DONE` implemented, the rest answering 501), the error table, and the two generated tables in `api-v2.md`."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
START = '<!-- api-m1:start -->'
END = '<!-- api-m1:end -->'
V2_TABLES = {'implemented': ('<!-- api2-implemented:start -->', '<!-- api2-implemented:end -->'),
             'pending': ('<!-- api2-pending:start -->', '<!-- api2-pending:end -->')}
PIECES = ('M.11a', 'M.11b', 'M.11c', 'M.11d')


def load_yaml(text):
    """Load the entire contract safely, rejecting duplicate keys at any depth."""
    import yaml

    class UniqueKeyLoader(yaml.SafeLoader):
        def construct_mapping(self, node, deep=False):
            self.flatten_mapping(node)
            mapping = {}
            for key_node, value_node in node.value:
                key = self.construct_object(key_node, deep=deep)
                if key in mapping:
                    raise yaml.constructor.ConstructorError(
                        'while constructing a mapping', node.start_mark,
                        f'duplicate key {key!r}', key_node.start_mark)
                mapping[key] = self.construct_object(value_node, deep=deep)
            return mapping

    return yaml.load(text, Loader=UniqueKeyLoader)


def check_v1():
    try:
        import yaml
        import jsonschema  # noqa: F401 — required by the generated contract harness
    except ImportError as error:
        print(f'API contract check blocked: install requirements-dev.txt ({error.name} missing).', file=sys.stderr)
        return 2
    try:
        spec = load_yaml((ROOT / 'docs/brickwork/openapi-v1.yaml').read_text())
    except yaml.YAMLError as error:
        print(f'Invalid API contract YAML: {error}', file=sys.stderr)
        return 1
    rows = ['| Implemented operation | Backing |', '|---|---|']
    for path, operations in spec['paths'].items():
        for method, operation in operations.items():
            if isinstance(operation, dict) and operation.get('x-milestone') in ('M1', 'M2', 'M3', 'M4', 'M5', 'M6', 'M7'):
                rows.append(f"| `{method.upper()} /api/v1{path}` | `{operation['x-backing']}` |")
    generated = '\n'.join(rows)
    doc = ROOT / 'docs/brickwork/api-v1.md'
    text = doc.read_text()
    before, remainder = text.split(START, 1)
    existing, after = remainder.split(END, 1)
    if '--write' in sys.argv:
        doc.write_text(before + START + '\n' + generated + '\n' + END + after)
    elif existing.strip() != generated:
        print('API operation table differs from YAML; run scripts/check_api_contract.py --write.', file=sys.stderr)
        return 1
    print('API implemented operation table matches OpenAPI.')
    return 0


def v2_routes():
    """`{(METHOD, template): (endpoint, view)}` of the /api/v2 rules of a bare app, templates as the contract writes them."""
    import re
    from flask import Flask
    from brickwork.api2 import PREFIX, register
    app = Flask('check-api-contract')
    register(app)
    routes = {}
    for rule in app.url_map.iter_rules():
        if rule.rule.startswith(PREFIX + '/'):
            template = re.sub(r'<([^>]+)>', r'{\1}', rule.rule[len(PREFIX):])
            for method in rule.methods - {'HEAD', 'OPTIONS'}:
                routes[(method, template)] = (rule.endpoint, app.view_functions[rule.endpoint])
    return routes


def table(rows, header):
    return '\n'.join([header[0], header[1], *rows])


def check_v2(write):
    import yaml
    from brickwork.api2 import DONE
    from brickwork.core import errors
    try:
        spec = load_yaml((ROOT / 'docs/brickwork/openapi-v2.yaml').read_text())
    except yaml.YAMLError as error:
        print(f'Invalid API v2 contract YAML: {error}', file=sys.stderr)
        return 1
    problems = []
    if {k: v for k, v in spec['x-error-status'].items()} != dict(errors.HTTP_STATUS):
        problems.append('x-error-status differs from core.errors.HTTP_STATUS')
    operations, ids = {}, set()
    for path, methods in spec['paths'].items():
        for method, op in methods.items():
            if not isinstance(op, dict):
                continue
            if op['operationId'] in ids:
                problems.append(f"duplicate operationId {op['operationId']}")
            ids.add(op['operationId'])
            if op.get('x-piece') not in PIECES:
                problems.append(f"{method.upper()} {path}: x-piece {op.get('x-piece')!r} is not one of {PIECES}")
            operations[(method.upper(), path)] = op
    unknown_done = [p for p in DONE if p not in PIECES]
    if unknown_done:
        problems.append(f'api2.DONE names unknown pieces {unknown_done}')
    routes = v2_routes()
    for key in sorted(set(operations) - set(routes)):
        problems.append(f'{key[0]} {key[1]} is in the contract but not routed')
    for key in sorted(set(routes) - set(operations)):
        problems.append(f'{key[0]} {key[1]} is routed but not in the contract')
    implemented, pending = [], []
    for key, op in sorted(operations.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        if key not in routes:
            continue
        endpoint, view = routes[key]
        piece = getattr(view, 'piece', None)
        if op['x-piece'] in DONE:
            if piece is not None:
                problems.append(f'{key[0]} {key[1]}: piece {op["x-piece"]} is done but the route is a 501 placeholder')
            implemented.append(f"| `{key[0]} /api/v2{key[1]}` | {op['x-piece']} | `{view.__module__}.{view.__name__}` |")
        else:
            if piece != op['x-piece']:
                problems.append(f'{key[0]} {key[1]}: contract says {op["x-piece"]}, the route answers 501 for {piece!r}')
            pending.append(f"| `{key[0]} /api/v2{key[1]}` | {op['x-piece']} |")
    if endpoint_name_clash := [e for e in {r[0] for r in routes.values()} if e.count('.') != 1]:
        problems.append(f'odd endpoints {endpoint_name_clash}')
    generated = {'implemented': table(implemented, ('| Implemented operation | Piece | Backing |', '|---|---|---|')),
                 'pending': table(pending, ('| Operation (answers 501 until its piece lands) | Piece |', '|---|---|'))}
    doc = ROOT / 'docs/brickwork/api-v2.md'
    text = doc.read_text()
    for name, (start, end) in V2_TABLES.items():
        before, remainder = text.split(start, 1)
        existing, after = remainder.split(end, 1)
        if write:
            text = before + start + '\n' + generated[name] + '\n' + end + after
        elif existing.strip() != generated[name]:
            problems.append(f'api-v2.md {name} table differs from the contract; run scripts/check_api_contract.py --write')
    if write:
        doc.write_text(text)
    for problem in problems:
        print('API v2 contract: ' + problem, file=sys.stderr)
    if problems:
        return 1
    counts = {}
    for line in pending:
        piece = line.rsplit('|', 2)[1].strip()
        counts[piece] = counts.get(piece, 0) + 1
    print(f'API v2: {len(implemented)} operations implemented, {len(pending)} answer 501 until their piece lands '
          f'({", ".join(f"{p} {n}" for p, n in sorted(counts.items()))}); the contract, the routes and api-v2.md agree.')
    return 0


def main():
    code = check_v1()
    return check_v2('--write' in sys.argv) or code


if __name__ == '__main__':
    sys.exit(main())
