# Produce a minimal reproduction

Report a problem with enough evidence to distinguish graph declaration, data flow, runtime ownership and application effects.

1. Include Python/Jayrun versions, OS/backend, relevant settings and the exact invocation style (script, notebook or adopted event loop).
2. Reduce to complete imports, component declarations, graph construction/binding/confirmation, submission values and cleanup. Prefer a CPU value over a private dataset where the behavior is equivalent.
3. State the expected result and the observed exception or run/engine state. Preserve the causal exception and cleanup failures separately.
4. For a skipped route, show the connected producer values and output positions. For authority errors, show how authority and graph registration were supplied.
5. For remote work, include the relevant owner generation/revision sequence and transport delivery order without disclosing credentials or private payloads.
6. For a timing or concurrency issue, use Events/barriers that expose the ordering. A long sleep or one successful run does not establish a concurrency guarantee.

Include `run.report.data`, selected records and relevant pressure/history gap information when safe to disclose. Do not upload sensitive artifacts or a whole database by default. File a focused issue in the [public repository](https://github.com/jayrun-project/jayrun/issues).
