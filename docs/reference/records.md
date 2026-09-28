# Records, reports, events and progress

These returned values describe committed or captured evidence; they do not grant authority. Explicit records use ContextRecord. ContextValueStored is the event type associated with context value publication. See [records](../guides/evidence/records.md), [reports](../guides/evidence/reports.md), [events](../guides/evidence/progress.md) and [terminal history](../guides/runtime/history.md).

```{eval-rst}
.. autoclass:: jayrun.context.StepReference
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.context.ArtifactActor
   :members:
   :undoc-members:
```

```{eval-rst}
.. autoclass:: jayrun.context.ArtifactState
   :members:
   :undoc-members:
```

```{eval-rst}
.. autoclass:: jayrun.context.ArtifactRecord
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.context.RecordOrigin
   :members:
   :undoc-members:
```

```{eval-rst}
.. autoclass:: jayrun.context.ExecutionOutcome
   :members:
   :undoc-members:
```

```{eval-rst}
.. autoclass:: jayrun.context.ExecutionRecord
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.context.TimerRecord
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.context.MetricRecord
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.context.LogRecord
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.context.FailureRecord
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.context.AttemptRecord
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.context.ExecutionReport
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.context.StateTransition
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.context.StopRequested
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.context.IterationStarted
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.context.ControlRequested
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.context.EngineChanged
   :members:
```

```{eval-rst}
.. autodata:: jayrun.context.ContextHistoryEntry
```

```{eval-rst}
.. autoclass:: jayrun.context.CommandOrigin
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.context.EngineOrigin
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.context.RuntimeModuleOrigin
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.context.ContextOrigin
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.context.StepOrigin
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.context.ContextControlRequested
   :members:
```

```{eval-rst}
.. autodata:: jayrun.context.ContextEvent
```

```{eval-rst}
.. autoclass:: jayrun.context.ContextObserver
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.context.ContextReport
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.context.ContextStateChanged
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.context.ContextStopRequested
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.context.ContextTransferred
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.context.ContextValueStored
   :members:
```

```{eval-rst}
.. autoexception:: jayrun.context.ObserverOverflowError
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.context.PressureSnapshot
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.context.ProgressSnapshot
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.context.StepProgress
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.context.StepProgressState
   :members:
   :undoc-members:
```

```{eval-rst}
.. autoclass:: jayrun.context.ContextRecord
   :members:
```

```{eval-rst}
.. autoexception:: jayrun.context.OwnershipCapacityError
   :members:
```

```{eval-rst}
.. autoexception:: jayrun.context.ContextHistoryLimitError
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.context.TerminalCursor
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.context.TerminalSummary
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.context.TerminalHistoryPage
   :members:
```

## Structured record values

```{py:class} RecordValue

A descriptive recursive value type, not an application constructor: None, bool, int, finite float, str, tuples of supported values, or mappings with string keys and supported values. Input lists are detached into tuples; mappings become immutable snapshots. Unsupported application objects, cycles and excessive depth/size are rejected.
```

Keys are exact strings, at most 1024 UTF-8 bytes. Record nesting is bounded at 64 levels; context-level accounted-byte limits can reject a value earlier. See [record admission and retention](../guides/evidence/records.md).
