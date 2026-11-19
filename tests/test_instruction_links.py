"""Link out to a set's instructions (#465, ADR 0035): pure, no network."""
import pytest

from brickwork.core.instruction_links import DEFAULT_REGION, instruction_links
from brickwork.core.official_instructions import LOCALES


def urls(links):
    return {link['source']: link['url'] for link in links}


def test_current_set_with_a_suffix_and_a_region():
    links = instruction_links('75192-1', 'US')
    assert [link['source'] for link in links] == ['lego', 'rebrickable']
    assert urls(links) == {'lego': 'https://www.lego.com/en-us/service/building-instructions/75192?age-gate=grown_up',
                           'rebrickable': 'https://rebrickable.com/sets/75192-1/'}
    assert all(link['label'] for link in links)


def test_vintage_set_and_a_higher_suffix():
    assert urls(instruction_links('6086-2', 'GB')) == {
        'lego': 'https://www.lego.com/en-gb/service/building-instructions/6086?age-gate=grown_up', 'rebrickable': 'https://rebrickable.com/sets/6086-2/'}


def test_no_suffix_gets_one_for_rebrickable_only():
    result = urls(instruction_links('6086', 'DE'))
    assert result['rebrickable'] == 'https://rebrickable.com/sets/6086-1/' and '/6086?' in result['lego']


def test_default_region_and_every_locale():
    assert '/de-de/' in urls(instruction_links('1000-1'))['lego'] and DEFAULT_REGION == 'DE'
    for region, locale in LOCALES.items():
        assert f'/{locale}/' in urls(instruction_links('1000-1', region))['lego']


def test_every_url_is_plain_https():
    assert all(link['url'].startswith('https://') for link in instruction_links('1000-1', 'AT'))


@pytest.mark.parametrize('bad', ['', 'abc', '1000-', '-1', '1000-1-2', '1000-a', ' 1000-1', '1000-1\n', '10/00', None, 1000, '1000-1?x=1'])
def test_malformed_set_numbers_are_refused(bad):
    with pytest.raises(ValueError):
        instruction_links(bad, 'DE')


@pytest.mark.parametrize('region', ['XX', 'de', '', 5])
def test_an_unsupported_region_is_refused(region):
    with pytest.raises(ValueError, match='region'):
        instruction_links('1000-1', region)
