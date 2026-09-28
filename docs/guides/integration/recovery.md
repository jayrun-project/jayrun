# Recover computation and save checkpoints

Separate framework execution ownership from application checkpoint semantics. A synchronized graph-iteration boundary can carry continuation state; it does not automatically capture every mutation, random generator, file write or optimizer buffer.

For an application checkpoint, identify all state needed to resume: model parameters, optimizer/scheduler state, data position, random generators, domain version and validated configuration. Write it with the application's required atomicity and durability policy. Store a safe reference to it in records or artifacts where useful; do not put a large checkpoint in a bounded diagnostic record.

Replayed or retried work can repeat side effects. Use idempotency keys or transactional boundaries for externally visible writes. Runtime ownership fencing prevents obsolete owners from committing through the synchronization protocol; it does not undo a request already accepted by an external service.

Recovery claims should state the boundary: which committed iteration/checkpoint is available, what accepted work may repeat, what evidence is missing, and who performs re-admission. A Database of reports is evidence, not an automatic snapshot of live Python heap objects.

The [adapter checkpoint tutorial](../../tutorials/checkpointed-adapter-finetuning.md) demonstrates domain state selection; the [remote guide](remote.md) describes ownership transfer. Test interruption at the boundaries your application actually relies on.
