"""Invented Alex and Sam PDF fixtures. No network or global registry changes."""
from brickwork.core.instruction_sources import Candidate, Registry


class FakeAdapter:
    def __init__(self, source='rebrickable'):
        self.source, self.calls = source, []
        self.content = b'%PDF-1.4\nInvented Alex and Sam booklet\n%%EOF'
        self.failure = None

    def find(self, set_no, region):
        return [Candidate(self.source, n, 2, 'English', region, len(self.content),
                          f'https://invented.example/{set_no}/{n}.pdf', f'Alex and Sam · Booklet {n} of 2') for n in (1, 2)]

    def fetch(self, url, limit):
        self.calls.append((url, limit))
        if self.failure:
            raise self.failure
        return self.content


def registry(source='rebrickable'):
    fake = FakeAdapter(source)
    return Registry({source: fake}), fake
