"""Error routing through the real application factory (M.11a, issue #113: API v2 on the 4.0 fixtures).

A path under /api/v2 that does not exist or takes no such method is problem+json, not the web's HTML error page; the web keeps its own."""
from tests.api2 import PREFIX, call, v2  # noqa: F401
from tests.app4 import app4, coll, pair  # noqa: F401


def test_an_unknown_path_is_problem_json_not_the_web_error_page(v2):
    for method in ('get', 'post'):
        response = call(v2, '/does-not-exist', method)
        assert response.mimetype == 'application/problem+json', method
        assert response.json['code'] in ('not_found', 'method_not_allowed')
    assert call(v2, '/does-not-exist').json['code'] == 'not_found'
    assert call(v2, '/does-not-exist', token=None).json['code'] == 'not_found'      # routing happens before authentication


def test_a_wrong_method_lists_what_is_allowed(v2):
    response = call(v2, '/me', 'post')
    assert response.status_code == 405 and response.json['code'] == 'method_not_allowed'
    assert 'GET' in response.headers['Allow']


def test_the_web_keeps_its_own_404_page(v2):
    assert v2.get('/not-an-api-path').status_code == 404
    assert v2.get('/not-an-api-path').mimetype == 'text/html'


def test_an_item_id_that_is_not_a_number_is_a_problem_404(v2):
    for bad in ('abc', '0', '-1', '1.5', '9' * 30):
        response = call(v2, '/items/' + bad)
        assert response.status_code == 404 and response.json['code'] == 'not_found', bad
