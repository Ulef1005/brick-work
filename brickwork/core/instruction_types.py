"""Shared instruction discovery data, independent of source adapters."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Candidate:
    source: str
    booklet: int
    booklets: int
    language: str | None
    region: str | None
    size: int | None
    url: str
    label: str = 'Instructions'

