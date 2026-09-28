# Integrate external services and storage

Keep transport and application lifecycle policy outside the framework core. Use resources for reusable clients, artifacts for request/result data, and terminal operators for side effects that do not produce another graph value.

A request handler can build submission contexts, call an application-owned Engine and await a `ContextRun`. Decide whether client cancellation should leave work running, request Stop or request abort. Cancelling a waiter alone is not a resource-cleanup policy.

A resource's setup acquires its client and returns `Data`; teardown closes it. Cleanup partial setup locally if construction fails before return. Sharing a client requires an explicit concurrency policy; a framework binding does not make a third-party client thread-safe.

For result publication, define idempotency and acknowledgments at the service/storage boundary. A successful `record()` call only queues evidence. A graph retry can repeat an external write. Where correctness depends on an atomic business transition, implement it in that business store and record the resulting identifier.

The [image service](../../tutorials/denoise-images-with-fastapi.md) and [document service](../../tutorials/document-ingestion.md) tutorials illustrate application integration. Their HTTP and storage choices are examples, not new core requirements.
