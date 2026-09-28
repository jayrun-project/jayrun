# self.placement

Reserve capacity before side effects: waiting may restart the invocation. Leases do not allocate or move payloads. [Placement model](../model/placement.md) and [capacity guide](../guides/runs/capacity.md).

Read [how to use self.placement](../guides/components/placement.md) for hook availability and a worked explanation. This is an injected handle, not an application constructor.

```{py:class} PlacementInterface
```

```{py:method} PlacementInterface.reserve(*, device, backend, memory_gb, exclusive=False, device_id=None)

Reserve capacity on one accelerator device.

:param device: Requested device family.
:param backend: Required accelerator backend.
:param memory_gb: Memory to reserve in decimal gigabytes.
:param exclusive: Require exclusive use of the device.
:param device_id: Optional exact device index.
```

[Source: reserve](https://github.com/jayrun-project/jayrun/blob/main/jayrun/engine/interfaces/placement.py)

```{py:method} PlacementInterface.reserve_group(*, device, backend, group_memory_gb=0, per_device_memory_gb=0, max_devices, min_devices=1, prefer_max_devices=False, exclusive=False)

Reserve a homogeneous group of accelerator devices.

`group_memory_gb` may be distributed across the group, while
`per_device_memory_gb` is required on every selected device.
```

[Source: reserve_group](https://github.com/jayrun-project/jayrun/blob/main/jayrun/engine/interfaces/placement.py)

```{py:method} PlacementInterface.cuda(memory_gb, *, exclusive=False, device_id=None)

Reserve one CUDA GPU; shorthand for `reserve`.
```

[Source: cuda](https://github.com/jayrun-project/jayrun/blob/main/jayrun/engine/interfaces/placement.py)

```{py:method} PlacementInterface.cuda_group(*, group_memory_gb=0, per_device_memory_gb=0, max_devices, min_devices=1, prefer_max_devices=False, exclusive=False)

Reserve a CUDA GPU group; shorthand for `reserve_group`.
```

[Source: cuda_group](https://github.com/jayrun-project/jayrun/blob/main/jayrun/engine/interfaces/placement.py)

```{py:attribute} PlacementInterface.placement_requests

A tuple of placement requests made through this interface in invocation order. Use it for inspection of the current setup/execute session; it is not a list of all engine reservations. Request objects describe the requested device, capacity and execution identity.
```

[Source: placement_requests](https://github.com/jayrun-project/jayrun/blob/main/jayrun/engine/interfaces/placement.py)
