"""CSV that a spreadsheet opens as text (#67).

Notes and remarks come from imported order files and old databases; a cell starting with =, +, -, @,
a tab or a carriage return would run as a formula in Excel or LibreOffice. Such text cells get a
leading apostrophe. Numbers are written as they are.
"""
import csv
import re

TRIGGERS = ('=', '+', '-', '@', '\t', '\r')
NUMBER = re.compile(r'[+-]?\d+(\.\d+)?')  # money and counts formatted as text, such as -2.00


def cell(value):
    if isinstance(value, str) and value.startswith(TRIGGERS) and not NUMBER.fullmatch(value):
        return "'" + value
    return value


class Writer:
    def __init__(self, stream):
        self._out = csv.writer(stream)

    def writerow(self, row):
        return self._out.writerow([cell(v) for v in row])

    def writerows(self, rows):
        for row in rows:
            self.writerow(row)


def writer(stream):
    return Writer(stream)
