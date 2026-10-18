"""Display-only selection and history from recorded v3 observations."""
import calendar
import json
from functools import lru_cache
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from .sources.base import now


def priority(db):
    row = db.execute("SELECT value FROM settings WHERE key='source_priority'").fetchone()
    return json.loads(row[0]).get('market_price', {}) if row else {}


def dated(value):
    # Observation stamps repeat across rows and across sorts; parse each distinct string once.
    try:
        return _dated(value)
    except TypeError:  # unhashable value
        return _parse(value)


@lru_cache(maxsize=8192)
def _dated(value):
    return _parse(value)


def _parse(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result
    except (ValueError, AttributeError):
        return None


def choose(rows, kind, priorities, condition=None, *, prefer_sold=False):
    """Source priority first; freshest successful observation within that source."""
    sources = [s.split(':')[0] for s in priorities.get(kind, priorities.get('*', ['bricklink']))]
    candidates = [r for r in rows if not r.get('error') and r.get('price') is not None
                  and (condition is None or r.get('condition') == condition)]
    candidates.sort(key=lambda r: (dated(r.get('observed_at')) or datetime.min.replace(tzinfo=timezone.utc), r.get('id', r.get('observation_id', 0))), reverse=True)
    if prefer_sold:
        candidates.sort(key=lambda r: r['guide'] != 'sold')
    candidates.sort(key=lambda r: sources.index(r['source']) if r['source'] in sources else len(sources))
    return candidates[0] if candidates else None


def condition_rows(rows, kind, priorities):
    market = [r for r in rows if r['guide'] in ('sold', 'stock') and r.get('slot') != 'boxed']
    return [p for condition in ('U', 'N') if (p := choose(market, kind, priorities, condition, prefer_sold=True))]


def history(rows, selected):
    if not selected or selected['condition'] != 'U' or selected['guide'] != 'sold':
        return None
    end = now()
    month = (end.year * 12 + end.month - 1) - 6
    year, month = divmod(month, 12)
    start = end.replace(year=year, month=month+1, day=min(end.day, calendar.monthrange(year, month+1)[1]))
    points = []
    # Compare only one source/currency/region/slot. Never join unlike series.
    for row in rows:
        if row.get('error') or any(row.get(k) != selected.get(k) for k in ('source', 'currency', 'region', 'slot', 'condition', 'guide')):
            continue
        date = dated(row.get('observed_at'))
        try:
            value = Decimal(row['price'])
        except (InvalidOperation, TypeError):
            continue
        if date and start <= date <= end and value.is_finite() and value >= 0:
            points.append(dict(date=date, value=value, id=row.get('id', 0)))
    points.sort(key=lambda p: (p['date'], p['id']))
    if not points:
        return None
    if len({p['date'] for p in points}) < 2:
        # #32: one date is a single price point, shown as text; a line needs two.
        last = points[-1]
        return dict(single=True, points=[dict(date=last['date'].isoformat(), value=str(last['value']))],
                    currency=selected['currency'] or 'Currency not recorded', source=selected['source'])
    low, high = min(p['value'] for p in points), max(p['value'] for p in points)
    # Rounded down axis start is labelled explicitly; equal values remain flat.
    floor = low.to_integral_value(rounding='ROUND_FLOOR')
    ceiling = max(high.to_integral_value(rounding='ROUND_CEILING'), floor+1)
    span = (end-start).total_seconds()
    for p in points:
        p['x'] = round((p['date']-start).total_seconds()/span*300, 2)
        p['y'] = round(float(70-(p['value']-floor)/(ceiling-floor)*60), 2)
        p['date'] = p['date'].isoformat()
    return dict(points=points, polyline=' '.join(f"{p['x']},{p['y']}" for p in points), low=str(floor), high=str(ceiling), currency=selected['currency'] or 'Currency not recorded', source=selected['source'])
