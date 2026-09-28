# Submission and configuration errors

If `submit()` raises before returning, no ContextRun is available from that call. Correct the input and retry deliberately; failed normalization leaves the caller's builder contexts unchanged. If it returns a rejected run, inspect that run's state/report instead.

| Symptom | Inspect | Resolution |
| --- | --- | --- |
| Unconfirmed graph | `graph.confirmed` and preparation errors | Bind required resources/timing choices, confirm explicitly, then submit |
| Unknown declaration/ID or foreign definition | Which graph owns the supplied reference | Use that graph's declarations or inspection references |
| Missing required artifact/config | Entry and configuration definitions | Supply the required value; omission is not a generated value |
| Config `value_type` or exact-type error | Field type and supplied Python type | Use bool/int/float/str/tuple exactly; resolve library types from primitive declarations |
| Config nesting/bytes/nodes error | Portable-value bounds | Reduce declaration size; move bulk data to artifacts/resources |
| Registered identity missing/conflicting | Registry key, version and exact graph | Register the intended confirmed graph and authority scopes |
| Serializer coverage error | Entry/exit boundary | Bind complete required coverage before graph confirmation |
| Engine not accepting work | Engine state and shutdown/failure | Finish diagnosis/cleanup and submit to an appropriate running owner |

`None`, omission and default are not interchangeable. Optional configuration can represent absent data within its field rules; required values still need valid inputs. `False` is not an exact `int`. See [configuration](../graphs/configuration.md), [registration](../graphs/registration.md) and the [builder reference](../../reference/artifacts.md).
