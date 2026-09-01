(placement-interface)=
# Placement Interface

`self.placement` requests accelerator capacity for the current invocation. A successful request returns an immutable, inspectable `Placement` or `PlacementGroup`.

A placement is a lease over runtime-managed capacity. It is not a device object, not a worker selection API, and not another execution scope.

This page documents the invocation-facing `self.placement` capability. For allocator behavior, admission, contention, and placement value types, see {doc}`Placement and Capacity <../runtime/placement-and-capacity>`.

Ordinary CPU data uses Jayrun's default CPU placement. Explicit reservation is intended for declared accelerator capacity.

## Request placement before performing work

Issue every placement request at the beginning of `execute()` or resource `setup()`, before expensive computation, external side effects, or device allocation:

```python
def execute(self) -> Data:
    placement = self.placement.cuda(memory_gb=2)

    tensor = load_and_move_tensor(
        self.input_data.value,
        device=f"cuda:{placement.device_id}",
    )
    return Data(value=tensor, placement=placement)
```

If capacity is temporarily unavailable, Jayrun exits the current invocation through an internal placement-control signal. After capacity is reconciled, the method may be invoked again **from the beginning**. Any work performed before the request could therefore be repeated.

:::{important}
Placement acquisition is a restart boundary. Calculate only the lightweight arguments needed for the request first, issue all requests in a deterministic order, and begin side-effecting or expensive work only after every required placement has been returned.
:::

## Single-device requests

Use `reserve()` when exactly one accelerator is required:

```python
from jayrun import Data
from jayrun.placement import Backend, Device


def execute(self) -> Data:
    placement = self.placement.reserve(
        device=Device.GPU,
        backend=Backend.CUDA,
        memory_gb=2,
    )
    tensor = create_tensor(device=f"cuda:{placement.device_id}")
    return Data(value=tensor, placement=placement)
```

Optional arguments include:

- `exclusive=True` to require exclusive use of the selected device;
- `device_id=N` to require a particular device.

Attach the returned placement to the `Data` that uses the reservation. This ties the lease lifetime to the artifact or resource data that requires it.

## Placement-group requests

Use `reserve_group()` when one execution may use several homogeneous accelerators:

```python
group = self.placement.reserve_group(
    device=Device.GPU,
    backend=Backend.CUDA,
    group_memory_gb=8,
    per_device_memory_gb=1,
    min_devices=2,
    max_devices=4,
    prefer_max_devices=True,
)
```

This requests:

- between `min_devices` and `max_devices`;
- `group_memory_gb` distributed across the selected group;
- an additional `per_device_memory_gb` on every selected device;
- the largest feasible group when `prefer_max_devices=True`.

Set `min_devices` and `max_devices` to the same value to require an exact device count.

`group_memory_gb` describes total memory required by the workload as a whole. `per_device_memory_gb` describes memory duplicated on every selected device. Keeping these terms separate avoids ambiguous “memory per group” behavior.

## Inspecting placements uniformly

`Placement` and `PlacementGroup` are distinct types but share a common inspection surface:

| Property | `Placement` | `PlacementGroup` |
|---|---|---|
| `placements` | One-item tuple containing itself | Tuple of group members |
| `primary` | Itself | First group member |
| `device_ids` | Zero- or one-item tuple | All selected device IDs |
| `reserved_memory_bytes` | Reserved bytes on the device | Total reserved bytes across members |

A `PlacementGroup` is also a sequence:

```python
for placement in group:
    print(placement.device_id, placement.memory_bytes)

first = group[0]
device_ids = group.device_ids
```

Code that only needs location information may accept either type and inspect the shared properties. Code that needs individual devices should retain the distinction and iterate the group explicitly.

## CUDA helpers

CUDA workloads can use shorter forms:

```python
placement = self.placement.cuda(
    memory_gb=2,
    exclusive=False,
)

group = self.placement.cuda_group(
    group_memory_gb=8,
    min_devices=2,
    max_devices=4,
    prefer_max_devices=True,
)
```

`cuda()` and `cuda_group()` change only the request syntax. Allocation, waiting, inspection, and lease lifetime remain the same.

## Waiting for capacity

If capacity is temporarily unavailable, Jayrun moves the execution into placement waiting and restarts the invocation after reconciliation finds capacity. User code does not poll or sleep.

If the request is impossible under the runtime's declared devices, the execution fails according to the configured failure policy.

:::{important}
Placement requests must remain deterministic across retries. The same execution path must issue the same requests in the same order with the same arguments. Jayrun uses that identity to suspend and safely restart the invocation.
:::

Do not catch the internal placement-unavailable signal or implement a custom retry loop. Let it unwind the invocation, then allow the engine to manage restart, reconciliation, and release.

## Lease lifetime

The runtime allocator owns capacity, while placement-bearing artifact or resource data keeps its lease alive. Capacity becomes reclaimable when no live holder still requires the placement. There is intentionally no public manual `release()` method, because explicit release could invalidate data that still refers to the device allocation.

:::{warning}
Do not discard a placement while live data still depends on its reserved device capacity. Attach the placement to the corresponding {py:class}`jayrun.Data` instance so the lease follows the data lifetime.
:::

## API reference

```{py:class} PlacementInterface
Execution-facing capability for requesting accelerator capacity.
```

```{py:method} PlacementInterface.reserve(*, device, backend, memory_gb, exclusive=False, device_id=None) -> Placement
Request one accelerator placement.

:param Device device: Accelerator kind. CPU does not require reservation.
:param Backend backend: Device backend.
:param memory_gb: Positive decimal gigabytes to reserve.
:type memory_gb: int | float
:param bool exclusive: Whether the selected device must be exclusive to this lease.
:param device_id: Required non-negative device identifier, or `None` for allocator selection.
:type device_id: int | None
:raises TypeError: If an argument has an invalid type.
:raises ValueError: If memory, device identifiers, or request constraints are invalid.
```

```{py:method} PlacementInterface.reserve_group(*, device, backend, group_memory_gb=0, per_device_memory_gb=0, max_devices, min_devices=1, prefer_max_devices=False, exclusive=False) -> PlacementGroup
Atomically request a homogeneous group of accelerator placements.

:param Device device: Accelerator kind.
:param Backend backend: Device backend.
:param group_memory_gb: Total decimal gigabytes distributed across the group.
:type group_memory_gb: int | float
:param per_device_memory_gb: Additional decimal gigabytes reserved on every selected device.
:type per_device_memory_gb: int | float
:param int max_devices: Maximum acceptable device count.
:param int min_devices: Minimum acceptable device count.
:param bool prefer_max_devices: Try larger feasible groups before smaller ones.
:param bool exclusive: Whether every selected device must be exclusive to this lease.
:raises TypeError: If an argument has an invalid type.
:raises ValueError: If counts, memory, or request constraints are invalid.
```

```{py:method} PlacementInterface.cuda(memory_gb, *, exclusive=False, device_id=None) -> Placement
Equivalent to {py:meth}`PlacementInterface.reserve` with `Device.GPU` and `Backend.CUDA`.
```

```{py:method} PlacementInterface.cuda_group(*, group_memory_gb=0, per_device_memory_gb=0, max_devices, min_devices=1, prefer_max_devices=False, exclusive=False) -> PlacementGroup
Equivalent to {py:meth}`PlacementInterface.reserve_group` with `Device.GPU` and `Backend.CUDA`.
```

```{py:attribute} PlacementInterface.placement_requests
:type: tuple

Ordered placement requests issued by the current invocation. This diagnostic view also supports Jayrun's deterministic waiting and reconciliation protocol; application code normally uses the returned placements instead.
```


The {ref}`interface-safety` section summarizes the safety rules that apply to placement and the other operational interfaces.

Next, see {doc}`Placement and Capacity <../runtime/placement-and-capacity>` for the allocator and scheduler model.
