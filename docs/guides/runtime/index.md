# Use self.runtime to supervise work

Inside an operator's `execute()` or a resource's `setup()`, `self.runtime` provides engine identity and access to other runs according to the context's authority. Start with the [interface introduction](../components/index.md) if these injected handles are new to you.

An ordinary computation normally needs only its own inputs and `self.context`. Use a Supervisor to watch or control other runs; use a Controller when the component must also submit work or request engine shutdown. The application grants that role when submitting the graph.

```{toctree}
:maxdepth: 1

../../model/authority
capabilities
control
controller
correspondence
```

[History access](history.md) explains the separate grant for stored results. The [runtime reference](../../interfaces/runtime.md) lists every member.
