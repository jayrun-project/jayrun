# Choose between data, configuration and settings

Suppose an image-processing operator takes an image, applies a filter of radius `3`, and runs with two permitted attempts. These values belong to three different channels.

| Value | Channel | Who uses it? |
| --- | --- | --- |
| The image | Artifact input | The operator reads `self.image.value` |
| Filter radius | ConfigField and ConfigContext | The operator reads `self.radius.value` |
| Attempt limit | RetryPolicy in execution settings | Jayrun decides whether to retry |

Configuration is part of your computation's declaration. You name its fields and choose their types. Settings are predefined framework options. Changing worker capacity does not add an operator field, and declaring a field named `max_iterations` does not change the runtime iteration policy.

Use [configuration](../guides/graphs/configuration.md) for portable computational parameters and [execution settings](../guides/runs/settings.md) for EngineSettings and ContextSettings, including where each is passed.

## Configuration is fixed for one submission

An operator or resource declares a ConfigField. Submission resolves its supplied value or default into a sealed configuration view. The field's value is not consumed by artifact flow and does not change between that run's repeats or graph iterations. Use new submission values to choose a different configuration for another run.

Resource configuration participates in reuse: another run with compatible resource configuration may acquire the same cached value. Changing an operator-only parameter does not itself reconfigure a resource. [The lifetime example](lifetime.md#compare-three-submissions) demonstrates both cases.

## Other kinds of state

A tensor, document or evolving model belongs in an artifact. A reusable client or read-only model can be a managed resource. Small diagnostic values, such as a loss value or chosen branch, can be stored with `self.context.record()`. Large durable checkpoints belong in application storage.

Configuration accepts exact immutable built-in values. Records have a separate structured-value contract that also accepts supported lists and mappings. Choose the channel for its purpose first; [portable codecs](../guides/integration/values.md) explains how supported values cross an application boundary.
