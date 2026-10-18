"""Production WSGI entry point."""
import gevent.monkey
gevent.monkey.patch_all()
import logging
from app import create_app
from brickwork.settings import exposure_problem
application = create_app()
# Refuse to serve an install that anyone on the network could edit, unless that is chosen (#60).
if problem := exposure_problem(application.config):
    raise SystemExit(problem)
if not application.config['AUTHENTICATION_PASSWORD']:
    logging.warning('Login is off (BW_ALLOW_NO_LOGIN): anyone who can reach Brick Work can edit it.')
