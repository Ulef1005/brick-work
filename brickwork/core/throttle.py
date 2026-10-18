"""Failed-login throttling per client (#48): after N failures, a delay that doubles up to a cap.

In-process and per worker: a restart forgets the counters, and several processes count separately.
That bounds guessing to a few attempts per delay without a shared store. Nothing submitted is kept.
"""
import logging
import os
import threading
import time

LOG = logging.getLogger('brickwork.auth')
CAP = 10000  # clients remembered; the oldest are dropped first


def _setting(name, default):
    value = os.environ.get(name, '')
    return int(value) if value.isdigit() and int(value) > 0 else default


class Throttle:
    def __init__(self, label, clock=time.monotonic):
        self.label, self.clock = label, clock
        self.lock = threading.Lock()
        self.clients = {}  # ip -> [failures, blocked_until, last_seen]

    @staticmethod
    def limits():
        return _setting('BW_LOGIN_MAX_FAILURES', 5), _setting('BW_LOGIN_MAX_DELAY', 300)

    def wait(self, client):
        """Whole seconds this client must wait before trying again; 0 when it may try now."""
        with self.lock:
            entry = self.clients.get(client)
            if not entry:
                return 0
            left = entry[1] - self.clock()
            return int(left) + (left % 1 > 0) if left > 0 else 0

    def fail(self, client):
        allowed, ceiling = self.limits()
        now = self.clock()
        with self.lock:
            self._expire(now, ceiling)
            entry = self.clients.setdefault(client, [0, 0.0, now])
            entry[0] += 1
            entry[2] = now
            if entry[0] >= allowed:
                entry[1] = now + min(2 ** (entry[0] - allowed), ceiling)
            failures = entry[0]
        LOG.warning('%s failed for %s (%d in a row)', self.label, client, failures)

    def succeed(self, client):
        with self.lock:
            self.clients.pop(client, None)

    def _expire(self, now, ceiling):
        if len(self.clients) < CAP:
            return
        idle = [c for c, e in self.clients.items() if now - e[2] > 2 * ceiling and e[1] <= now]
        for client in idle:
            del self.clients[client]
        while len(self.clients) >= CAP:
            del self.clients[min(self.clients, key=lambda c: self.clients[c][2])]


LOGIN = Throttle('Login')
API = Throttle('API token check')
