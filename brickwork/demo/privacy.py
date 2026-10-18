"""What must never reach the public tree, the demo or the Pages site.

The built-in patterns are generic: private LAN addresses, home folders and vault references. A
maintainer's own host names, domains and people are not written here, since this file is public:
they come from the file named by BW_PRIVATE_PATTERNS_FILE (one regular expression per line, # for
comments), which the maintainer's gate passes in and public CI does without.
"""
import os
import re
from pathlib import Path

# Home folders are matched case-sensitively, so a URL path such as github.com/users/<name> is not one.
GENERIC = (r'192\.168\.\d+\.\d+', r'(?-i:/Users/[A-Za-z])', r'(?-i:/home/[a-z])', r'op://')


def extra_patterns(path=None):
    path = path or os.environ.get('BW_PRIVATE_PATTERNS_FILE')
    if not path:
        return []
    lines = Path(path).expanduser().read_text(encoding='utf-8').splitlines()
    return [line.strip() for line in lines if line.strip() and not line.lstrip().startswith('#')]


def pattern(path=None):
    """One case-insensitive expression for the generic and the maintainer's private patterns."""
    return re.compile('|'.join((*GENERIC, *extra_patterns(path))), re.IGNORECASE)
