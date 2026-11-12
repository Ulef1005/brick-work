"""Value and gain (#57): `GET /valuation` (the copies and the Statistics figures) and `GET /export/insurance.csv` (the insurance report).

Both are `core/valuation.py`'s, read-only, in the display currency: a copy's price paid, its worth with the source and date of the quote, and
the gain; the totals count only the copies that have both a price paid and a worth."""
from flask import Response

from ..core import valuation
from . import route
from .read import arguments, reading, respond


@route('/valuation')
@reading
def get_valuation(db):
    """Every live copy with its price paid, worth and gain, and the Paid vs value figures of the Statistics screen."""
    arguments()
    return respond(valuation.valuation(db))


@route('/export/insurance.csv')
@reading
def get_export_insurance_csv(db):
    """The insurance report as CSV: one row per live copy, in set-number order, with the copy's own photo count (the photos are on the page)."""
    arguments()
    return Response(valuation.report_csv(db), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=brickwork-insurance-report.csv'})
