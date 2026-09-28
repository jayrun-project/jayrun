# ContextRun, states and results

Obtain ContextRun from submission or authorized runtime visibility; do not construct it. Waiting without a state means finalization, not success. See [waiting and control](../guides/runs/context-run.md) and [records/reports](records.md).

```{eval-rst}
.. autoclass:: jayrun.context.ContextRun()
   :members:
```

```{eval-rst}
.. autoclass:: jayrun.context.ContextState
   :members:
   :undoc-members:
```

```{eval-rst}
.. autoclass:: jayrun.context.ContextRequest
   :members:
   :undoc-members:
```

```{eval-rst}
.. autoclass:: jayrun.context.ContextSnapshot
   :members:
```

```{eval-rst}
.. autoexception:: jayrun.context.ContextNotTerminatedError
   :members:
```
