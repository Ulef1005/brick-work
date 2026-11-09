"""Which gate a change needs: the whole check (`full`) or the documentation check only (`docs`; #254, ADR 0024).

    python3 scripts/check_scope.py BASE HEAD     print `docs` when every file changed on HEAD since it left BASE is documentation, else `full`

.github/workflows/check.yml runs it for a pull request and hands the answer to scripts/check.sh as BW_CHECK_MODE. Standard library only.
Anything uncertain is `full`: no changed file, a SHA git cannot resolve (a new branch has an all-zero one), a diff that fails.

Documentation is `docs/`, `scripts/site/` (the Pages site's templates and styles), `mkdocs.yml`, `CHANGELOG.md` and `README.md`, with two exceptions:
`docs/brickwork/` and `docs/data-model-4.0/` hold the API and MCP contract, the cutover table and the schema design that app tests and
`scripts/check_api_contract.py` read, so a change there runs the whole gate. `design/` (the screen gate's baselines among it), `scripts/*.py`,
the workflow, the requirements and every line of app source also run the whole gate."""
import subprocess
import sys

PREFIXES = ('docs/', 'scripts/site/')
FILES = ('mkdocs.yml', 'CHANGELOG.md', 'README.md')
CONTRACTS = ('docs/brickwork/', 'docs/data-model-4.0/')


def is_documentation(path: str) -> bool:
    if path.startswith(CONTRACTS):
        return False
    return path in FILES or path.startswith(PREFIXES)


def scope(paths: list[str]) -> str:
    return 'docs' if paths and all(is_documentation(p) for p in paths) else 'full'


def changed(base: str, head: str) -> list[str]:
    """The files changed on `head` since the merge base with `base`; renames count as a delete and an add, so a file moved out of app source shows."""
    result = subprocess.run(['git', 'diff', '--name-only', '--no-renames', '-z', f'{base}...{head}'], capture_output=True, text=True)
    if result.returncode:
        return []
    return [p for p in result.stdout.split('\0') if p]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.splitlines()[0], file=sys.stderr)
        return 2
    print(scope(changed(*argv)))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
