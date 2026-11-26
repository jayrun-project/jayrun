# Record application values

Use `self.context.record(key, value)` for small structured application evidence. Read it through `self.context.records(key)` or an authorized `run.records(key)` handle. Unknown keys return an empty tuple.

```python
# Inside execute(), after computing a finite scalar loss:
self.context.record("loss", {"value": float(loss), "batch": 12})
```

This fragment assumes a supported record value and an executing component. [The Controller example](../runtime/controller.md) demonstrates complete record publication and reading after finalization.

## Acceptance and visibility

Recording validates and detaches the value before queueing commitment. Mutating an original list afterward does not change the accepted record. Return means queued acceptance, so an immediate `records()` call may still see the preceding committed snapshot. Shutdown or ownership transfer can discard pending requests. A record is not an acknowledgment that an external write succeeded.

Records include context, step, iteration, execution, attempt and sequence evidence. Use sequence identity/order rather than timestamps alone. `RecordPolicy.history_per_key` retains the latest N records for each key; absence of older records does not mean they never existed.

## Supported values and limits

Use portable primitives and supported list/tuple/dictionary structures. Non-finite floats, cycles, unsupported application objects and excessive nesting/size are rejected. The context’s `record_policy` bounds retained history per key, distinct keys, accounted bytes per value and retained-plus-pending total bytes. Accounting includes 16 bytes per node plus UTF-8 string bytes and integer magnitude bytes; it is not a measurement of Python heap allocation.

The default is 64 records per key. Set `ContextSettings(record_policy=RecordPolicy(history_per_key=1))` for the latest value per key, or use `history_per_key=None` to retain every admitted value. The key and byte budgets still apply. Capacity violations fail before queueing. Do not use records as unbounded tensor storage or a business database. See [portable codecs](../integration/values.md), [settings](../../reference/settings.md) and [record reference](../../reference/records.md).
