"""Check the implemented operation table against OpenAPI; --write refreshes it."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
START = '<!-- api-m1:start -->'
END = '<!-- api-m1:end -->'


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


def main():
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


if __name__ == '__main__':
    sys.exit(main())
