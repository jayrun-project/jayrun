(placement-and-capacity)=
# Placement and Capacity

Placement describes where runtime data lives and, for accelerators, carries a lease over declared device capacity. Operators and resource setup request placement through {py:class}`PlacementInterface`; the runtime allocator decides whether the request can be granted immediately, must wait, or is impossible.

Placement is not an execution scope. The request belongs to one execution, while the resulting lease may outlive that invocation when artifact or resource data still depends on it.

## Placement concepts

Jayrun separates four related concepts:

| Concept | Meaning |
|---|---|
| Runtime device | Capacity declared in {py:class}`jayrun.settings.RuntimeDevice` |
| Placement request | Requirements issued by the current execution |
| Placement | One selected device and its reserved memory |
| Placement group | An atomic homogeneous lease across several devices |

Ordinary CPU data uses `CPU_PLACEMENT` and requires no allocator reservation. Accelerator data should carry the placement returned by `self.placement`:

```python
return Data(value=tensor, placement=placement)
```

The runtime accounts for capacity; the application library still creates, moves, and executes the actual device objects.

## `Device` and `Backend`

{py:class}`Device` identifies a device kind:

- `CPU`
- `GPU`
- `TPU`

{py:class}`Backend` identifies the execution backend used with an accelerator:

- `CUDA`
- `MPS`
- `OPENCL`
- `ROCM`
- `XLA`
- `XPU`

A request matches only runtime devices that declare both its device kind and backend. CPU does not use a backend or explicit reservation.

## `Placement`

A {py:class}`Placement` describes one location:

```python
placement.device
placement.backend
placement.device_id
placement.memory_bytes
```

For an accelerator, `memory_bytes` is the capacity reserved on that device. For `CPU_PLACEMENT`, backend and device ID are `None`, and reserved memory is zero.

Applications normally obtain accelerator placements from {py:meth}`PlacementInterface.reserve` or a backend helper. Constructing a `Placement` directly describes a location but does not reserve runtime capacity.

## `PlacementGroup`

A {py:class}`PlacementGroup` is an immutable sequence of placements granted atomically for one request:

```python
for placement in group:
    print(placement.device_id, placement.memory_bytes)
```

All members share one device kind, backend, and lease. Device IDs are unique. The group records both the group-wide and per-device portions of the request.

Either the entire requested group is granted or no member is reserved. This prevents partial multi-device startup.

## Uniform placement inspection

`Placement` and `PlacementGroup` share a small inspection surface:

| Property | `Placement` | `PlacementGroup` |
|---|---|---|
| `placements` | One-item tuple containing itself | Tuple of group members |
| `primary` | Itself | First member |
| `device_ids` | Zero- or one-item tuple | Every selected device ID |
| `reserved_memory_bytes` | Its `memory_bytes` | Sum across all members |

Code that needs one primary location can accept either type:

```python
location = data.placement
primary = location.primary
device_ids = location.device_ids
```

Code that shards data must preserve the distinction and iterate `location.placements`.

## Reserving one device

Request one accelerator from the {doc}`Placement Interface <../interfaces/placement>`:

```python
from jayrun.placement import Backend, Device


placement = self.placement.reserve(
    device=Device.GPU,
    backend=Backend.CUDA,
    memory_gb=2,
)
```

Use `device_id=N` when one exact runtime device is required. Otherwise, the allocator selects a compatible device with sufficient capacity.

CUDA has a shorter equivalent:

```python
placement = self.placement.cuda(memory_gb=2)
```

## Reserving a device group

Use one atomic group request for homogeneous multi-device work:

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

The equivalent CUDA helper is {py:meth}`PlacementInterface.cuda_group`.

Group requests cannot target one `device_id`; selection is performed across compatible runtime devices. Use a single-device request when an exact device ID is required.

## `min_devices` and `max_devices`

The acceptable device count is inclusive:

- equal values request an exact count;
- different values allow elastic selection;
- `prefer_max_devices=False` tries counts from minimum to maximum;
- `prefer_max_devices=True` tries counts from maximum to minimum.

```python
group = self.placement.cuda_group(
    group_memory_gb=6,
    min_devices=2,
    max_devices=2,
)
```

This requires exactly two CUDA devices. A structurally compatible but currently occupied pair causes waiting; a runtime with fewer than two compatible devices makes the request impossible.

## Memory requirements

Single-device `memory_gb` is the total capacity reserved on that device.

Group requests distinguish:

- `group_memory_gb`: total memory divided across the selected devices;
- `per_device_memory_gb`: additional memory reserved independently on every device.

For $n$ devices, total reserved capacity is:

$$
\text{group memory} + n \times \text{per-device memory}.
$$

Group memory is distributed as evenly as possible, including any remaining bytes. Request values are decimal gigabytes and are rounded upward to whole bytes; declared runtime capacity is rounded downward.

A non-exclusive request must reserve positive memory. An exclusive request may reserve zero bytes because it reserves the whole device-access mode rather than sharing capacity.

:::{important}
Declare capacity requirements conservatively. Jayrun accounts for requested limits; it does not measure framework-specific tensor allocation before each kernel.
:::

## Exclusive placement

Set `exclusive=True` when no other placement may share the selected device:

```python
placement = self.placement.cuda(
    memory_gb=2,
    exclusive=True,
)
```

An exclusive request succeeds only when the device has no live reservations. While the exclusive lease exists, shared and other exclusive requests cannot use that device.

A {py:class}`jayrun.settings.RuntimeDevice` with `exclusive_only=True` applies the same exclusivity requirement to every request routed to that device, even when the request itself uses `exclusive=False`.

## Placement waiting and reconciliation

A placement request has three internal outcomes:

- **success**: capacity is reserved and returned;
- **unavailable**: compatible total capacity exists, but it is currently occupied;
- **impossible**: no declared runtime-device combination can satisfy the request.

Unavailable capacity moves the step session into placement waiting. The context reflects that waiting state, but independent ready routes in the same context may continue dispatching.

When capacity is released, resource eviction becomes possible, or the periodic coordinator runs, Jayrun reconciles pending requests. A resolved session resumes from the beginning of its placement-call sequence; prior calls must therefore be identical.

:::{important}
Placement requests must be deterministic across restarts: the same calls, in the same order, with the same arguments. Jayrun rejects a changed request sequence because previous reservations could no longer be matched safely.
:::

Impossible requests fail the execution and then follow its retry and failure policies. Applications should not catch Jayrun's internal placement-control exceptions to implement polling loops.

## Reservation lifetime

Accelerator placements carry an internal shared lease. Capacity remains reserved while any live `Placement` or `PlacementGroup` from that lease is reachable.

Attach the returned location to the data that uses it:

```python
return Data(value=model, placement=placement)
```

Artifact clearing, resource eviction, context cleanup, or application reference release may make the lease unreachable. A weak-reference finalizer then queues capacity release and wakes reconciliation.

There is no public `release()` method. Manual release could invalidate an artifact or resource whose payload still resides on the device.

:::{warning}
Do not attach CPU placement to accelerator-resident data or discard placement metadata while the payload remains live. Capacity accounting follows the placement lease, not the library tensor object.
:::

## Placement contention

For each acceptable device count, the allocator selects compatible devices with sufficient total capacity. It uses a best-fit choice based on remaining bytes, with device ID as a deterministic tie-breaker.

If active reservations block a request, the request waits. If idle cached resources hold the relevant placements, Jayrun may tear down enough of them to satisfy the request. Eviction prefers plans that remove fewer resources and release less excess capacity.

Multi-request wait cycles can occur when sessions hold earlier placements while waiting for later ones. Reconciliation detects such cycles, revokes selected victim-session placements, and restarts their placement sequences so another session can progress.

This recovery provides progress under detected cycles; it is not a user-configurable fairness or priority policy.

## Scheduler admission

Before a submitted context begins execution, the context scheduler applies two pressure gates:

1. **CPU memory pressure.** Admission pauses above an 85% high watermark and resumes after recovery below a 75% low watermark.
2. **Known placement pressure.** A graph with learned requirements is held when those requirements share device/backend capacity with pending placement requests.

The CPU monitor uses the CPU `RuntimeDevice.memory_limit_gb` when supplied; otherwise it uses available process, system, and cgroup information. This CPU limit controls admission pressure, not a `Placement` reservation.

Admission is runtime-wide. A queued context is reconsidered periodically and whenever placement history changes.

## Placement history

Jayrun records normalized placement requirements observed for each graph declaration during the current runtime. History includes successful requests and requests that entered placement waiting.

The scheduler uses this history to avoid admitting another occurrence of the same graph into capacity already under pressure. It learns from execution: before a graph has issued its first placement request, no placement history is available for predictive admission.

Placement history is internal, runtime-local, and cleared at shutdown. It is neither durable profiling data nor a public graph declaration.

## Multi-device Torch usage

Jayrun reserves capacity and reports device IDs; PyTorch still controls model replication, tensor movement, streams, and collectives. A multi-device model resource can retain replicas with one group lease:

```python
import copy

from jayrun import Data


def setup(self) -> Data:
    group = self.placement.cuda_group(
        group_memory_gb=self.group_memory_gb.value,
        per_device_memory_gb=self.per_device_memory_gb.value,
        min_devices=2,
        max_devices=4,
        prefer_max_devices=True,
    )
    model = load_model(self.model_path.value)
    replicas = tuple(
        copy.deepcopy(model).to(f"cuda:{placement.device_id}").eval()
        for placement in group
    )
    return Data(value=replicas, placement=group)
```

An operator can shard a batch across the retained replicas:

```python
def execute(self) -> Data:
    group = self.models.placement
    shards = self.batch.value.chunk(len(group.placements))
    outputs = tuple(
        model(shard.to(f"cuda:{placement.device_id}"))
        for model, shard, placement in zip(
            self.models.value,
            shards,
            group.placements,
            strict=True,
        )
    )
    return Data(value=outputs, placement=group)
```

This example uses one process and explicit replicas. For `DistributedDataParallel`, the application must still establish the process group and process-per-device execution model. A placement group is a capacity lease, not a distributed launcher.

## API reference

Request methods are documented under {doc}`Placement Interface <../interfaces/placement>`.

```{py:class} Device
Device-kind enumeration containing `CPU`, `GPU`, and `TPU`.
```

```{py:class} Backend
Accelerator-backend enumeration containing `CUDA`, `MPS`, `OPENCL`, `ROCM`, `XLA`, and `XPU`.
```

```{py:class} Placement(device, backend=None, device_id=None, memory_bytes=0)
Immutable description of one device location and its capacity lease.

:param Device device: Device kind.
:param backend: Accelerator backend, or `None` for CPU.
:type backend: Backend | None
:param device_id: Non-negative accelerator identifier, or `None` for CPU.
:type device_id: int | None
:param int memory_bytes: Non-negative reserved bytes.
:raises TypeError: If an argument has an invalid type.
:raises ValueError: If CPU or accelerator constraints are inconsistent.
```

```{py:attribute} Placement.device
:type: Device

Device kind.
```

```{py:attribute} Placement.backend
:type: Backend | None

Accelerator backend, or `None` for CPU.
```

```{py:attribute} Placement.device_id
:type: int | None

Accelerator device identifier, or `None` for CPU.
```

```{py:attribute} Placement.memory_bytes
:type: int

Capacity reserved on this device.
```

```{py:attribute} Placement.placements
:type: tuple[Placement, ...]

One-item tuple containing this placement.
```

```{py:attribute} Placement.primary
:type: Placement

This placement itself.
```

```{py:attribute} Placement.device_ids
:type: tuple[int, ...]

Zero- or one-item tuple containing the accelerator ID.
```

```{py:attribute} Placement.reserved_memory_bytes
:type: int

Alias for `memory_bytes`.
```

```{py:class} PlacementGroup(placements, group_memory_bytes=0, per_device_memory_bytes=0, prefer_max_devices=False)
Immutable sequence of homogeneous placements sharing one atomic lease.

:param tuple placements: Non-empty tuple of unique accelerator placements.
:param int group_memory_bytes: Group-wide memory distributed across members.
:param int per_device_memory_bytes: Additional memory reserved on every member.
:param bool prefer_max_devices: Whether the originating request preferred larger groups.
:raises TypeError: If an argument has an invalid type.
:raises ValueError: If membership, memory, or lease constraints are inconsistent.
```

```{py:attribute} PlacementGroup.placements
:type: tuple[Placement, ...]

Ordered group members.
```

```{py:attribute} PlacementGroup.group_memory_bytes
:type: int

Group-wide reserved-memory component.
```

```{py:attribute} PlacementGroup.per_device_memory_bytes
:type: int

Per-device reserved-memory component.
```

```{py:attribute} PlacementGroup.prefer_max_devices
:type: bool

Whether the originating request preferred larger feasible groups.
```

```{py:attribute} PlacementGroup.primary
:type: Placement

First group member.
```

```{py:attribute} PlacementGroup.device
:type: Device

Shared device kind.
```

```{py:attribute} PlacementGroup.backend
:type: Backend

Shared accelerator backend.
```

```{py:attribute} PlacementGroup.device_ids
:type: tuple[int, ...]

All selected accelerator IDs.
```

```{py:attribute} PlacementGroup.reserved_memory_bytes
:type: int

Total reserved bytes across all members.
```

```{py:data} CPU_PLACEMENT
:type: Placement

Canonical zero-capacity CPU location used by default {py:class}`jayrun.Data`.
```

```{py:data} PlacementLocation
:type: type

Type alias for `Placement | PlacementGroup`.
```


Next, read {doc}`Engine and Context Lifecycle <engine-and-context-lifecycle>` for submission, waiting, retention, and shutdown behavior. Execution limits and runtime-device declarations are configured under {doc}`Execution Settings <../settings/execution-settings>`.
