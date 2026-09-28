# Reserve capacity with self.placement

Placement connects the Engine's capacity description with allocation performed by your application. First the application describes the available devices. Then an operator or resource setup requests a reservation. Finally your backend allocates or moves the payload.

## Describe a device in EngineSettings

For an application with a CUDA GPU at backend-visible index 0, this declares a 2 GB reservation budget:

```python
from jayrun import Engine
from jayrun.placement import Backend, Device
from jayrun.settings import EngineSettings, RuntimeDevice

settings = EngineSettings(runtime_devices=(
    RuntimeDevice(device=Device.GPU, backends=(Backend.CUDA,),
                  device_id=0, memory_limit_gb=2.0),
))
engine = Engine(settings=settings)
```

Start and close that Engine using the [normal lifecycle](../runs/engine.md). This declaration does not discover free VRAM or install CUDA. Choose a budget appropriate to the device and workload.

## Reserve before allocating

A resource can reserve capacity in setup and attach the reservation to the Data it returns. This example from the inference tutorial loads a model and moves it with PyTorch:

```{literalinclude} ../../../tutorials/mnist_inference.py
:language: python
:pyobject: ModelResource
```

`self.placement.cuda(memory_gb=.15)` returns a Placement whose device ID can be passed to the backend. Returning `Data(value=model, placement=placement)` carries that location and lease with the resource. The CPU branch requires no accelerator reservation. An operator follows the same pattern when producing a placed artifact.

A temporarily unavailable request can cause Jayrun to invoke the hook again from its beginning. Keep the reservation sequence stable, request capacity before externally visible effects, and avoid accumulating allocations across attempts. An impossible request cannot fit the configured devices and fails instead of becoming possible through waiting.

## Groups and lifetime

`cuda_group()` and `reserve_group()` request a homogeneous group atomically. `group_memory_gb` is a total budget distributed across the group; `per_device_memory_gb` is additional capacity required on each selected device. Your application decides how to split actual computation across those devices.

A retained resource or placed artifact may keep its lease alive. Pausing a run does not necessarily release its model or reservation. See [capacity and retention](../runs/capacity.md) when diagnosing waiting work.

The [placement model](../../model/placement.md) gives the units and ownership rules. The [interface reference](../../interfaces/placement.md) lists all reservation arguments and the current invocation's request view.

```{toctree}
:hidden:

../../model/placement
```
