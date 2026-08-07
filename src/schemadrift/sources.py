"""Read JSON samples out of the shapes real capture files actually come in.

Three layouts cover almost everything people have lying around: newline
delimited JSON from a log pipeline, a top-level array from a paginated API
dump, and a single object from a one-off ``curl``. The format is detected, not
configured, because being asked to declare it is a papercut.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator


class SampleError(ValueError):
    """Raised when a sample file cannot be read as JSON."""


def parse_samples(text: str, *, origin: str = "<string>") -> list[Any]:
    """Decode ``text`` into a list of samples.

    A top-level JSON array is treated as a list of samples; any other single
    JSON document is one sample; otherwise the text is read as NDJSON.
    """
    stripped = text.strip()
    if not stripped:
        return []

    try:
        document = json.loads(stripped)
    except json.JSONDecodeError:
        return _parse_ndjson(stripped, origin)

    return list(document) if isinstance(document, list) else [document]


def _parse_ndjson(text: str, origin: str) -> list[Any]:
    samples: list[Any] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            samples.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise SampleError(f"{origin}:{lineno}: invalid JSON: {exc.msg}") from exc
    if not samples:
        raise SampleError(f"{origin}: no JSON samples found")
    return samples


def load_samples(path: str | Path) -> list[Any]:
    """Read samples from a file, or from stdin when ``path`` is ``-``."""
    if str(path) == "-":
        import sys

        return parse_samples(sys.stdin.read(), origin="<stdin>")
    file_path = Path(path)
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SampleError(f"cannot read {file_path}: {exc.strerror}") from exc
    return parse_samples(text, origin=str(file_path))


def iter_paths(paths: list[str]) -> Iterator[Any]:
    """Yield every sample across several files, in order."""
    for path in paths:
        yield from load_samples(path)
