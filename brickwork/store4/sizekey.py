"""The size key of a catalogue name ("Plate 2 x 1" and "Plate 1 x 2" -> "1x2"), shared by the 3.3 size search and the 4.0 catalogue
builder. Lives in store4 because store4 must not import `core` (M.8a, issue #110); see `core/size_search.py` for the search."""
import re

NUM = r'(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)'
SEP = r'\s*[x×*]\s*'
IN_NAME = re.compile(rf'(?<![\w./])({NUM}){SEP}({NUM})(?:{SEP}({NUM}))?(?![\w/])', re.I)


def _number(text):
    text = text.strip()
    if '/' in text:
        whole, _, fraction = text.rpartition(' ')
        a, b = fraction.split('/')
        value = (float(whole) if whole else 0.0) + float(a) / float(b)
    else:
        value = float(text)
    return value


def _fmt(value):
    return str(int(value)) if value == int(value) else format(value, 'g')


def key_of(dims):
    try:
        return 'x'.join(_fmt(v) for v in sorted(_number(d) for d in dims if d))
    except (ValueError, ZeroDivisionError):
        return None


def name_key(name):
    """The size key of a catalogue name, or None."""
    match = IN_NAME.search(name or '')
    return key_of(match.groups()) if match else None
