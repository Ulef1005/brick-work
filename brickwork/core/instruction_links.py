"""Link out to a set's instructions (#465, ADR 0035): the pages where the user downloads the PDF, which the existing upload then takes.

No network call, no page renderer, no scraping: the links are built from the set number alone."""
import re

from .official_instructions import LOCALES, page_url

DEFAULT_REGION = 'DE'


def instruction_links(set_no, region=None):
    """`[{source, label, url}]` for a set number such as `6086-1`, `10497` or `COMCON034-1`: LEGO's instructions page for `region` first, then
    Rebrickable's set page. LEGO's page exists only for a purely numeric number, so an alphanumeric one (a promotional set) returns the
    Rebrickable link alone.

    `region` is a key of `LOCALES` (`None` means `DEFAULT_REGION`); a malformed number or an unsupported region is a `ValueError`.
    The Rebrickable pattern `https://rebrickable.com/sets/<number>-<n>/` is NOT verified against the live site (it refuses scripted
    requests); Ulf is to confirm it in a browser (ADR 0035). A number without a suffix gets `-1`.
    A number that is not `[A-Za-z0-9]+` with an optional `-N` is a `ValueError`."""
    number = re.fullmatch(r'([A-Za-z0-9]+)(-\d+)?', set_no) if isinstance(set_no, str) else None
    if not number:
        raise ValueError('Choose a set number such as 6086-1')
    region = DEFAULT_REGION if region is None else region
    if not isinstance(region, str) or region not in LOCALES:
        raise ValueError('Choose a supported region: ' + ', '.join(LOCALES))
    full = number[1] + (number[2] or '-1')
    links = [{'source': 'rebrickable', 'label': 'Rebrickable set page', 'url': f'https://rebrickable.com/sets/{full}/'}]
    if number[1].isdigit():
        links.insert(0, {'source': 'lego', 'label': 'Official instructions', 'url': page_url(set_no, region)})
    return links
