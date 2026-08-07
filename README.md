# schemadrift

**Infer a JSON schema from real payloads, then find out who a change breaks.**

Most API drift is discovered in production, by a consumer. `schemadrift` reads
the payloads you already have — a log dump, an NDJSON capture, a `curl` output —
infers their structure, and diffs two captures into a list of changes tagged
`BREAKING`, `ADDITIVE`, or `NEUTRAL`.

Zero dependencies. Python 3.9+. Standard library only.

Work in progress — see the open pull requests.

## License

MIT
