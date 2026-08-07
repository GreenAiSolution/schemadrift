"""Command line entry point: ``schemadrift infer`` and ``schemadrift diff``."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence, TextIO

from . import __version__
from .diff import (
    ADDITIVE,
    BREAKING,
    CONSUMER,
    HIGH,
    NEUTRAL,
    PRODUCER,
    SEVERITY_ORDER,
    DiffReport,
    diff,
)
from .infer import infer
from .sources import SampleError, iter_paths

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_ERROR = 2

_FAIL_ON = {"breaking": BREAKING, "additive": ADDITIVE, "any": NEUTRAL, "never": None}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="schemadrift",
        description="Infer JSON schemas from real payloads and tell you who a "
        "change breaks.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_infer = sub.add_parser("infer", help="print the schema inferred from samples")
    p_infer.add_argument("files", nargs="+", help="sample files (- for stdin)")
    p_infer.add_argument("--indent", type=int, default=2, help="JSON indent")

    p_diff = sub.add_parser("diff", help="compare two sets of samples")
    p_diff.add_argument("old", help="baseline samples (- for stdin)")
    p_diff.add_argument("new", help="current samples")
    p_diff.add_argument(
        "--role",
        choices=[CONSUMER, PRODUCER],
        default=CONSUMER,
        help="consumer: you read this data (default). producer: you send it.",
    )
    p_diff.add_argument(
        "--min-samples",
        type=int,
        default=20,
        help="observations needed before a change is high confidence",
    )
    p_diff.add_argument(
        "--include-low-confidence",
        action="store_true",
        help="let low-confidence changes affect the exit code",
    )
    p_diff.add_argument(
        "--fail-on",
        choices=sorted(_FAIL_ON),
        default="breaking",
        help="lowest severity that exits non-zero (default: breaking)",
    )
    p_diff.add_argument("--json", action="store_true", help="emit JSON")
    return parser


def _run_infer(args: argparse.Namespace, out: TextIO) -> int:
    schema = infer(iter_paths(args.files)).to_json_schema()
    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", **schema}
    print(json.dumps(schema, indent=args.indent), file=out)
    return EXIT_OK


def render(report: DiffReport, *, include_low: bool) -> str:
    """Human-readable report, ordered worst-first."""
    if not report.changes:
        return "No drift detected."

    lines = [f"Comparing as {report.role} (you "
             f"{'read' if report.role == CONSUMER else 'send'} this data)", ""]
    ranked = sorted(
        report.changes,
        key=lambda c: (-SEVERITY_ORDER[c.severity], c.confidence != HIGH, c.path),
    )
    for change in ranked:
        lines.append(f"  {change}")

    lines.append("")
    counts = [
        f"{len(report.of_severity(sev, include_low=include_low))} {sev}"
        for sev in (BREAKING, ADDITIVE, NEUTRAL)
    ]
    lines.append("  ".join(counts))
    return "\n".join(lines)


def _run_diff(args: argparse.Namespace, out: TextIO) -> int:
    old = infer(iter_paths([args.old]))
    new = infer(iter_paths([args.new]))
    report = diff(old, new, role=args.role, min_samples=args.min_samples)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2), file=out)
    else:
        print(render(report, include_low=args.include_low_confidence), file=out)

    threshold = _FAIL_ON[args.fail_on]
    if threshold is None:
        return EXIT_OK
    qualifying = [
        change
        for change in report
        if (args.include_low_confidence or change.confidence == HIGH)
        and SEVERITY_ORDER[change.severity] >= SEVERITY_ORDER[threshold]
    ]
    return EXIT_DRIFT if qualifying else EXIT_OK


def main(argv: Sequence[str] | None = None, out: TextIO | None = None) -> int:
    out = out or sys.stdout
    args = build_parser().parse_args(argv)
    try:
        if args.command == "infer":
            return _run_infer(args, out)
        return _run_diff(args, out)
    except SampleError as exc:
        print(f"schemadrift: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
