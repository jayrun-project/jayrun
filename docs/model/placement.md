# Placement and capacity

Placement describes where application data resides and accounts for reserved execution capacity. It does not allocate tensors, move objects, configure a model backend or measure actual device memory use.

`RuntimeDevice` describes the devices an Engine may manage. `self.placement.reserve()` or `.cuda()` requests a lease; group operations request a homogeneous group atomically. `Data` can carry the resulting placement metadata. The application allocates or moves its payload using its backend.

An impossible request cannot fit the configured device set. A temporarily unavailable request can fit but must wait for capacity. That wait can restart the invocation; keep the placement-call sequence stable and perform external effects only after admission. Do not catch internal placement signals to continue without a lease.

Memory reservations use decimal gigabytes (`1 GB = 1,000,000,000 bytes`). Persistence and record settings ending in `_bytes` count different storage/accounting budgets; do not compare them as one global memory cap.

CPU execution is available without an accelerator lease. Reserving a CUDA lease does not prove that CUDA is installed or that the application allocation will succeed. See [manage capacity](../guides/runs/capacity.md) and the [placement interface reference](../interfaces/placement.md).
