"""Shared presentation text for Toni pages; stored values stay unchanged."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
import math
import re

from .part_size import NUMBER


def money(value, currency='EUR', signed=False, precision=2, fixed=False):
    """Format money with word differences, unspaced symbols and spaced labels.

    ``fixed=True`` keeps all decimals (two by default); precision and stored
    values are unchanged. Missing values use an em dash; other text passes through.
    """
    if value is None or value == '':
        return '—'
    try:
        amount = Decimal(str(value)).quantize(Decimal(1).scaleb(-precision))
        if not amount.is_finite():
            return str(value)
    except (InvalidOperation, ValueError):
        return str(value)
    direction = ' below' if amount < 0 else ' above' if signed and amount > 0 else ''
    number = format(abs(amount), f',.{precision}f')
    if not fixed and number.endswith('.' + '0' * precision):
        number = number[:-(precision + 1)]
    currency = {'€': 'EUR', '$': 'USD', '£': 'GBP'}.get(currency, currency)
    currency = currency or ''
    label = currency if currency == 'Currency not recorded' else currency.upper()
    prefix = {'EUR': '€', 'USD': '$', 'GBP': '£'}.get(currency.upper(), label + ' ' if label else '')
    return prefix + number + direction


def short_date(value, with_time=False):
    if not value:
        return 'Date not recorded'
    try:
        date = (datetime.fromtimestamp(value) if isinstance(value, (int, float)) else
                value if isinstance(value, datetime) else
                datetime.fromisoformat(str(value).replace('/', '-').replace('Z', '+00:00')))
    except (ValueError, TypeError, OverflowError):
        return 'Date not recorded'
    months = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')
    if with_time:
        day = 'today' if date.date() == datetime.now().date() else f'{date.day} {months[date.month - 1]}'
        return f'{day}, {date:%H:%M}'
    return f'{date.day} {months[date.month - 1]} {date.year}'


def short_stamp(value, with_time=False):
    """"16 Oct" or "16 Oct · 09:12" for a stored timestamp; a lone dash when there is none."""
    if not value:
        return '—'
    try:
        date = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('/', '-').replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return '—'
    months = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')
    text = f'{date.day:02d} {months[date.month - 1]}'
    return f'{text} · {date:%H:%M}' if with_time else text


def source_label(source):
    return {'bricklink': 'BrickLink', 'bricklink_stock': 'BrickLink',
            'brickset': 'Brickset', 'manual': 'Manual'}.get(source, 'Unknown source')


def source_line(quote, slot=''):
    source = quote.get('source')
    label = source_label(source)
    condition = (quote.get('slot') or slot).removeprefix('bricklink_')
    if condition in ('new', 'used'):
        label += ' ' + condition
    if source in ('bricklink', 'bricklink_stock'):
        label += ' · ' + ('listings, not sales' if source == 'bricklink_stock' else 'sold average')
    return label + ' · ' + short_date(quote.get('observed_at'))


def missing_counts(parts, figures):
    return ' / '.join(f"{count} {noun if count == 1 else noun + 's'} missing"
                      for count, noun in ((parts, 'part'), (figures, 'figure')) if count)


def watch_scale(observed, maximum):
    """Zero-based ceiling, with ~25% headroom rounded up to a readable tick."""
    target = max(observed, maximum) * 1.25
    if target <= 0:
        return 1
    step = 10 ** math.floor(math.log10(target))
    return math.ceil(target / step) * step


def plural(count, noun, plural_noun=None):
    return f"{count} {noun if count == 1 else plural_noun or noun + 's'}"


def short_age(value):
    text = short_date(value)
    return text.rsplit(' ', 1)[0] if text != 'Date not recorded' else 'Age not recorded'


def difference(value, precision=0, suffix='', below='missing', above='surplus'):
    """Unsigned display count/difference; preserve missing and nonnumeric text."""
    if value is None or value == '':
        return '—'
    try:
        number = Decimal(str(value)).quantize(Decimal(1).scaleb(-precision))
        if not number.is_finite():
            return str(value)
    except (InvalidOperation, ValueError):
        return str(value)
    direction = below if number < 0 else above if number > 0 else ''
    return format(abs(number), f'.{precision}f') + suffix + (' ' + direction if direction else '')


def ratio(value, short=False):
    """Display gain per unit spent without a numeric sign."""
    if value is None or value == '':
        return '—'
    try:
        amount = Decimal(str(value))
        if not amount.is_finite():
            return str(value)
    except (InvalidOperation, ValueError, TypeError):
        return str(value)
    word = 'lost' if amount < 0 else 'gained'
    number = difference(value, precision=2, below='', above='')
    return f'{number}× {word}' if short else f'{number} {word} per 1 spent'


# Mirror part_size's dimension grammar; retain decimal commas in display names.
_TAIL_NUMBER = NUMBER.replace(r'\d', '[0-9]').replace(r'\.', '[.,]')
_TAIL_DIMENSIONS = re.compile(
    rf'(^|\s)({_TAIL_NUMBER}\s*[x×]\s*{_TAIL_NUMBER}(?:\s*[x×]\s*{_TAIL_NUMBER})?)$',
    re.I,
)


def part_name(value):
    """Use a mid-dot for a dimension separator; never alter catalogue identity."""
    return re.sub(r' - (?=[0-9])', ' · ', '' if value is None else str(value))


def nowrap_tail(value):
    """Keep a trailing dimension group, or the final two words, together."""
    text = '' if value is None else str(value)
    dimensions = _TAIL_DIMENSIONS.search(text)
    if dimensions:
        return text[:dimensions.start(2)] + re.sub(r'\s', '\u00a0', dimensions.group(2))
    head, separator, tail = text.rpartition(' ')
    return head + '\u00a0' + tail if separator else text
