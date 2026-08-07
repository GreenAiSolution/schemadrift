# schemadrift

**Infer a JSON schema from real payloads, then find out who a change breaks.**

Most API drift is discovered in production, by a consumer. `schemadrift` reads
the payloads you already have — a log dump, an NDJSON capture, a `curl` output —
infers their structure, and diffs two captures into a list of changes tagged
`BREAKING`, `ADDITIVE`, or `NEUTRAL`.

Zero dependencies. Python 3.9+. Standard library only.

## The idea

"Breaking" isn't a property of a change. It's a property of a change **plus who
you are**.

Adding `null` to a response field breaks every consumer that reads it and costs
the producer nothing. Adding a required request field is the exact mirror: free
for the consumer, breaking for the producer. Tools that ignore this either cry
wolf on every diff or stay silent through real outages.

So every change kind carries two severities, and you pick the role that matches
the direction of the data:

| Change | `--role consumer` (you read it) | `--role producer` (you send it) |
| --- | --- | --- |
| field removed | **breaking** | additive |
| new required field | additive | **breaking** |
| new optional field | additive | additive |
| required → optional | **breaking** | additive |
| optional → required | additive | **breaking** |
| type widened (`string` → `string\|null`) | **breaking** | additive |
| type narrowed | additive | **breaking** |
| type replaced (`int` → `string`) | **breaking** | **breaking** |
| new enum value | **breaking** | additive |
| enum value dropped | additive | **breaking** |
| enum → free-form | **breaking** | additive |
| free-form → enum | additive | **breaking** |
| format changed | neutral | neutral |

The table is deliberately antisymmetric. That's the whole design.

## Install

```bash
pip install -e .
```

## Use

Diff two captures:

```console
$ schemadrift diff examples/orders-v1.ndjson examples/orders-v2.ndjson
Comparing as consumer (you read this data)

  BREAKING $.customer.email  field removed
  BREAKING $.status  new values refunded
  BREAKING $.total  now also null
  ADDITIVE $.currency  new required field
  NEUTRAL  $.created_at  format date -> date-time

3 breaking  1 additive  1 neutral
```

Exit code is `1` when a change at or above `--fail-on` (default `breaking`) is
found, so it drops straight into CI:

```yaml
- run: schemadrift diff baseline.ndjson $(mktemp).ndjson
```

Flip the role and the severities invert — the dropped field and the new enum
value stop mattering, while the field you now have to *send* becomes the
problem:

```console
$ schemadrift diff examples/orders-v1.ndjson examples/orders-v2.ndjson --role producer
Comparing as producer (you send this data)

  BREAKING $.currency  new required field
  ADDITIVE $.customer.email  field removed
  ADDITIVE $.status  new values refunded
  ADDITIVE $.total  now also null
  NEUTRAL  $.created_at  format date -> date-time

1 breaking  3 additive  1 neutral
```

Same two files, opposite verdict. Run both and you know exactly which side of
the wire has work to do.

Or just print the inferred schema:

```console
$ schemadrift infer examples/orders-v2.ndjson
```

`--json` gives machine-readable output for both commands.

## Inference is honest about small samples

A schema inferred from 4 payloads is a guess. Every change carries a
`confidence`, and by default low-confidence findings are *reported but do not
fail the build* — they're more likely sampling noise than real drift.

```console
$ schemadrift diff tiny-v1.ndjson tiny-v2.ndjson
  BREAKING $.b  field removed (low confidence)
```

Tune with `--min-samples N` (default 20), or `--include-low-confidence` to let
them count.

Enums work the same way: a field is only called an enum when its values repeat
enough to be evidence. Two distinct values over two samples is a coincidence,
not a closed set.

## Library

```python
from schemadrift import infer, diff

old = infer(json.loads(line) for line in open("v1.ndjson"))
new = infer(json.loads(line) for line in open("v2.ndjson"))

for change in diff(old, new, role="consumer"):
    print(change.severity, change.path, change.detail)
```

## Input formats

Detected, not configured — NDJSON, a top-level JSON array, or a single JSON
document. `-` reads stdin.

## Tests

```bash
python -m unittest discover -s tests -v
```

## License

MIT
