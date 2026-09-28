# Persistence, readers, queries and storage errors

Use [history storage](../guides/evidence/persistence.md) for ownership, flush, gaps and async usage. DatabaseReader is borrowed through Database.reader(); its constructor is not an application capability factory. Limits ending in _bytes count the budget named by that setting, not all process memory.

```{eval-rst}
.. autoclass:: jayrun.persistence.Database
   :members:
   :undoc-members:
```

```{eval-rst}
.. autoclass:: jayrun.persistence.DatabaseReader()
   :members:
   :undoc-members:
```

```{eval-rst}
.. autoclass:: jayrun.persistence.DatabaseStatus
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.persistence.Backend
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.persistence.DatabaseLimits
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.persistence.RetentionPolicy
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.persistence.ContextHistoryEntry
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.persistence.ContextHistoryHeader
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.persistence.EngineSessionRecord
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.persistence.EngineSessionHeader
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.persistence.HistoryQuery
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.persistence.SessionQuery
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.persistence.HistoryPage
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.persistence.SerializedLayout
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.persistence.DiagnosticCodec
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.persistence.ValueLimits
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.persistence.ValueMarker
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.persistence.ValueSnapshot
   :members:
```

```{eval-rst}
.. autofunction:: jayrun.persistence.encode_value
```

```{eval-rst}
.. autoexception:: jayrun.persistence.PersistenceError
   :members:
```

```{eval-rst}
.. autoexception:: jayrun.persistence.StorageContractError
   :members:
```

```{eval-rst}
.. autoexception:: jayrun.persistence.StorageUnavailable
   :members:
```

```{eval-rst}
.. autoexception:: jayrun.persistence.PersistenceBackpressure
   :members:
```

```{eval-rst}
.. autoexception:: jayrun.persistence.PersistenceTimeout
   :members:
```

```{eval-rst}
.. autoexception:: jayrun.persistence.PersistenceFlushError
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.persistence.LegacyImportRecord
   :members:
```

```{eval-rst}
.. autofunction:: jayrun.persistence.import_legacy
```
