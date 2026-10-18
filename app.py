"""Brick Work standalone Flask entry point."""
from flask import Flask
from brickwork.app import setup_app


def create_app():
    app = Flask(__name__)
    setup_app(app)
    return app


if __name__ == '__main__':
    app = create_app()
    from brickwork.settings import exposure_problem
    if problem := exposure_problem(app.config):
        raise SystemExit(problem)
    app.run(host=app.config['HOST'], port=app.config['PORT'], debug=app.config['DEBUG'])
