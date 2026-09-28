# Configure execution settings

Use settings to change how Jayrun manages execution. Use [ConfigField and ConfigContext](../graphs/configuration.md) for parameters your operator reads as part of its calculation.

## Engine settings and context settings

`EngineSettings` is supplied when creating the Engine. It chooses engine-wide behavior such as worker capacity, managed devices and failure policy. `ContextSettings` is supplied to `submit()` for one run. It chooses iteration, repetition, record and artifact-retention policy.

This fragment uses the confirmed graph and declarations from the [guided workflow](../../start/first-graph.md):

```python
from jayrun import ArtifactContext, ConfigContext, Engine
from jayrun.settings import ContextSettings, EngineSettings, RetryPolicy

engine_settings = EngineSettings(max_workers=2)
context_settings = ContextSettings(
    max_iterations=1,
    retry_policy=RetryPolicy(max_attempts=2, retry_on=(OSError,)),
)
with Engine(settings=engine_settings) as engine:
    run = engine.submit(
        graph,
        ArtifactContext({source: 7}),
        ConfigContext({scale.factor: 3}),
        settings=context_settings,
    )
    run.wait(timeout=5)
```

The factor remains `3`, regardless of worker capacity or retry count. Jayrun uses the retry policy if an invocation raises OSError; the policy does not ask Scale to multiply twice. The initial invocation counts as the first attempt. Check the outcome after waiting, as in the workflow.

## Defaults and overrides

With no settings arguments, Jayrun uses `EngineSettings()` and `ContextSettings()`. Settings use keyword arguments and are validated at construction.

A context's `retry_policy=None` inherits the Engine retry policy. Other context fields, such as `max_iterations`, use their own defaults; there is no general merge of every Engine setting into ContextSettings. The default context executes one graph iteration. Repetition must be requested by the operator, even when the repeat cap is unlimited.

| Change you want | Setting to choose | Read next |
| --- | --- | --- |
| Run multiple graph iterations | Context `max_iterations` | [Repeat and iterate](iteration.md) |
| Limit operator-requested repetitions | Context `max_repeats` | [Execution interface](../components/execution.md) |
| Keep only selected final outputs | Context `artifact_policy` | [Capacity and retention](capacity.md) |
| Keep the last few values for each record key | Context `record_history_limit` | [Records](../evidence/records.md) |
| Stop the Engine when ordinary execution fails | Engine `failure_mode` | [Failure handling](failures.md) |
| Describe accelerator capacity | Engine `runtime_devices` | [Placement interface](../components/placement.md) |

## Choosing limits

`None`, zero and omission have field-specific meanings. For example, `max_iterations=None` allows unbounded iteration, while `max_repeats=0` prevents additional executions. Do not assume zero disables every limit. The [settings reference](../../reference/settings.md) lists exact defaults, units and exhaustion behavior.

Start with the defaults, then change the policy associated with the need you have identified. Retry policy matters particularly for operations with external effects: a second attempt may repeat a write. See [retries and shutdown](failures.md) before enabling retries for those operations.
