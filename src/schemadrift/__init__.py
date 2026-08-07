"""schemadrift - infer JSON schemas from real payloads and classify the drift."""

from __future__ import annotations

__version__ = "0.1.0"

from .infer import Node, infer  # noqa: E402
from .sources import SampleError, load_samples, parse_samples  # noqa: E402

__all__ = [
    "__version__",
    "Node",
    "SampleError",
    "infer",
    "load_samples",
    "parse_samples",
]
