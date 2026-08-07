"""schemadrift - infer JSON schemas from real payloads and classify the drift.

>>> from schemadrift import infer, diff
>>> old = infer([{"id": 1, "state": "open"}] * 30)
>>> new = infer([{"id": 1, "state": None}] * 30)
>>> [c.severity for c in diff(old, new)]
['breaking', 'breaking']
"""

from __future__ import annotations

__version__ = "0.1.0"

from .diff import (  # noqa: E402
    ADDITIVE,
    BREAKING,
    CONSUMER,
    NEUTRAL,
    PRODUCER,
    Change,
    DiffReport,
    diff,
)
from .infer import Node, infer  # noqa: E402
from .sources import SampleError, load_samples, parse_samples  # noqa: E402

__all__ = [
    "__version__",
    "ADDITIVE",
    "BREAKING",
    "CONSUMER",
    "Change",
    "DiffReport",
    "NEUTRAL",
    "Node",
    "PRODUCER",
    "SampleError",
    "diff",
    "infer",
    "load_samples",
    "parse_samples",
]
