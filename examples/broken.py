"""A file with both kinds of problem, for trying the tool out.

Nothing here needs anything installed -- every import is from the standard library -- so
`hedgemony examples/broken.py` gives the same full result on any machine, straight after
cloning, with nothing set up.

Expected: three invented names and one stated example that does not hold.
"""
import json
import math
from json import JSONEncoder


def pages_needed(items, per_page):
    """How many pages are needed to show every item.

    >>> pages_needed(10, 3)
    4
    """
    # Ten items at three per page needs four pages. This gives three: every name in the line
    # exists, so nothing but the stated example above can catch it.
    return math.floor(items / per_page)


def middle(values):
    return math.median(values)               # math has no median


def save(data):
    return json.serialise(data)              # json exports dumps, not serialise


def encode(data):
    encoder = JSONEncoder()
    return encoder.encode_fast(data)         # JSONEncoder has no encode_fast
