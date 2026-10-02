```{eval-rst}
.. meta::
   :description: Build a controllable Python document-ingestion service around Jayrun with bounded admission, inspection, review, cancellation and transactional publication.
```

(tutorial-document-ingestion)=
# Controllable Document Ingestion

Build a background document job service with inspection, review, cancellation, bounded
admission, duplicate-submission handling, and transactional index publication. This is
application code composed around Jayrun, not a new transport or database feature in the core.

## Run it

```bash
python -m tutorials.document_ingestion
uvicorn tutorials.document_ingestion:create_app --factory
```

Open `tutorials/05_document_ingestion.ipynb`. `create_app(storage=...)` opts into a persistent
application-owned SQLite directory. Omitting storage gives an ephemeral demonstration.

## Process one document

The artifact starts as a `DocumentWork`. Parsing removes HTML markup and script/style text,
then produces bounded word chunks. A review flag requests pause after parsing. An immutable
shared hashing encoder produces normalized lexical vectors; a serialized index resource
publishes them in one SQLite transaction.

```{literalinclude} ../../tutorials/document_ingestion.py
:language: python
:pyobject: build_graph
```

The hashing encoder is real deterministic lexical retrieval, **not a learned semantic
encoder**. It needs no model download and makes the entire service runnable offline. Replacing
it with a learned encoder requires preserving the resource's thread-safety, model/version,
and placement contract; test the replacement against those requirements.

## Interact through HTTP

`POST /jobs` returns HTTP 202 and a content-derived job identifier. Repeating the same text
and format returns that existing job even when admission is full. `GET /jobs/{id}` reports
state. `POST /jobs/{id}/wait?paused=true` waits for review, and `/resume` continues it.
`/wait` waits for terminal finalization; its timeout does not cancel. `/cancel` requests
abort and waits for drainage. `GET /search?q=...` searches published chunks.

The default app allows four active jobs and retains at most 1,000 job rows/handles.
Active-capacity exhaustion returns 429. Retained-history exhaustion returns 507; explicitly
`DELETE /jobs/{id}` after termination to delete the handle, job record, and indexed chunks.
These are count bounds, not a comprehensive byte/RSS quota. Essential terminal state is
retained in SQLite; live records have an explicit four-record-per-key limit.

```{literalinclude} ../../tutorials/document_ingestion.py
:language: python
:pyobject: run_demo
```

## Publication, failure, and restart

A short-lived SQLite connection owns each transaction and is explicitly closed. Index rows
and the publication receipt commit together. A failed insertion rolls back even after a
partial batch. Abort before publication leaves no published chunks; abort racing a commit
cannot undo an already committed external side effect. The API reports publication separately
from execution outcome for that reason.

At shutdown the application aborts live jobs and awaits both the engine and its tracked
finalization tasks. A clean completed job remains readable after restart. A stored accepted
job without a live owner becomes `interrupted`, not automatically resumed. Delete and resubmit
it explicitly. The default in-process setup is not a transactional distributed job queue.

Use one ASGI worker, add authentication and per-user job authorization before public exposure,
and choose an application-specific storage/retention policy. Exercise duplicate submission, cancellation and restart with your chosen storage before
using the service for important jobs. Multi-host coordination requires an application design
beyond this single-process example.

## Canonical source

The complete runnable implementation is [tutorials/document_ingestion.py](https://github.com/jayrun-project/jayrun/blob/main/tutorials/document_ingestion.py).
Use {doc}`the tutorial index <index>` for all notebooks and their execution requirements.
