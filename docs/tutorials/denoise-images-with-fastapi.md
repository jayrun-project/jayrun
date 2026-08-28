(tutorial-denoise-images-with-fastapi)=
# Denoise Images with FastAPI

This tutorial integrates Jayrun into a FastAPI application. A request can supply an image by URL or upload and choose whether to denoise it. One reusable graph then:

1. loads the image asynchronously;
2. routes it from a request-level configuration;
3. either removes isolated noise with NumPy or preserves the image;
4. returns a normalized PNG through FastAPI.

The example is deliberately small and non-AI. It shows why a graph is useful inside a web service: asynchronous I/O, synchronous CPU work, conditional execution, shared resources, and cleanup remain explicit without leaking those concerns into the endpoints.

## Install the dependencies

```bash
python -m pip install jayrun fastapi httpx numpy pillow uvicorn
```

## 1. Represent either input source

Both API routes submit the same graph. `ImageSource` tells the loader whether the bytes come from a URL or directly from the request body.

```python
from __future__ import annotations

import asyncio
import io
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
import numpy as np
from fastapi import FastAPI, HTTPException, Request, Response
from PIL import Image
from pydantic import BaseModel, HttpUrl

from jayrun import (
    Artifact,
    ArtifactContext,
    ArtifactField,
    ArtifactFlow,
    BaseOperator,
    BaseResource,
    ConfigContext,
    ConfigField,
    Data,
    Engine,
    GraphDefinition,
    ResourceField,
)
from jayrun.context import ContextState


MAX_IMAGE_BYTES = 10_000_000


@dataclass(frozen=True, slots=True)
class ImageSource:
    url: str | None = None
    content: bytes | None = None

    def __post_init__(self) -> None:
        if (self.url is None) == (self.content is None):
            raise ValueError("provide exactly one image source")


class ImageUrlRequest(BaseModel):
    url: HttpUrl
```

FastAPI constructs this application value; Jayrun transports it as the graph's entry artifact. The operators do not need to know which endpoint received the request.

## 2. Share one asynchronous HTTP client

```python
class HttpClientResource(BaseResource):
    requirements = ("httpx",)

    async def setup(self) -> Data:
        client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=10,
        )
        return Data(value=client)

    async def teardown(self, data: Data) -> None:
        await data.value.aclose()
```

The resource owns the connection pool for the engine runtime. Contexts can reuse connections instead of constructing and closing a client for every request.

Both lifecycle methods are asynchronous. Jayrun runs them on the application event loop and awaits client shutdown during engine cleanup.

## 3. Load the image asynchronously

```python
class LoadImage(BaseOperator):
    requirements = ("httpx",)

    def __init__(
        self,
        *,
        source: Artifact,
        outputs: tuple[Artifact | None, ...],
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name=name, description=description)
        self.source = ArtifactField(required=True)
        self.http_client = ResourceField(
            required=True,
            parallel_safe=True,
        )
        self.outputs = (ArtifactField(required=True),)

    async def execute(self) -> bytes:
        source = self.source.value

        if source.content is not None:
            content = source.content
        else:
            response = await self.http_client.value.get(source.url)
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            if not content_type.startswith("image/"):
                raise ValueError("URL did not return an image")

            content = response.content

        if not content:
            raise ValueError("image is empty")
        if len(content) > MAX_IMAGE_BYTES:
            raise ValueError("image exceeds the size limit")

        return content
```

An upload returns immediately from the same asynchronous operator. A URL awaits the shared client without blocking other FastAPI or Jayrun tasks.

`parallel_safe=True` is appropriate because `httpx.AsyncClient` supports concurrent requests and the operator does not mutate shared application state.

## 4. Route from request configuration

The router declares both possible outputs. The `denoise` configuration is set independently for every submitted context.

```python
class RouteImage(BaseOperator):
    def __init__(
        self,
        *,
        image: Artifact,
        outputs: tuple[Artifact | None, ...],
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name=name, description=description)
        self.image = ArtifactField(required=True)
        self.denoise = ConfigField(
            value_type=bool,
            required=True,
        )
        self.outputs = (
            ArtifactField(required=True),
            ArtifactField(required=True),
        )

    def execute(self) -> tuple[bytes | None, bytes | None]:
        if self.denoise.value:
            return self.image.value, None
        return None, self.image.value
```

Returning `None` marks that route unavailable. Jayrun skips any downstream operator that needs the unavailable artifact, so the application does not need an `if` statement around operator execution.

This is different from binding an output field to `None` while constructing the operator. A returned `None` makes a declared route inactive for one context; an unbound output removes that route from the graph definition.

| Request configuration | Active artifact | Operator that runs |
| --- | --- | --- |
| `denoise=True` | `image_to_denoise` | `DenoiseImage` |
| `denoise=False` | `image_to_preserve` | `EncodePng` |

## 5. Implement both branches

The selected denoise route runs a 3-by-3 median filter. It is effective for isolated salt-and-pepper noise and requires no model.

```python
class DenoiseImage(BaseOperator):
    requirements = ("numpy", "Pillow")

    def __init__(
        self,
        *,
        image: Artifact,
        outputs: tuple[Artifact | None, ...],
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name=name, description=description)
        self.image = ArtifactField(required=True)
        self.outputs = (ArtifactField(required=True),)

    def execute(self) -> bytes:
        image = Image.open(
            io.BytesIO(self.image.value)
        ).convert("RGB")
        values = np.asarray(image)

        padded = np.pad(
            values,
            ((1, 1), (1, 1), (0, 0)),
            mode="edge",
        )
        windows = np.lib.stride_tricks.sliding_window_view(
            padded,
            (3, 3),
            axis=(0, 1),
        )
        denoised = np.median(
            windows,
            axis=(-2, -1),
        ).astype(np.uint8)

        output = io.BytesIO()
        Image.fromarray(denoised).save(output, format="PNG")
        return output.getvalue()
```

The preservation route still decodes and encodes the input. This verifies that it is a valid image and ensures the response really is a PNG even when the upload was another format.

```python
class EncodePng(BaseOperator):
    requirements = ("Pillow",)

    def __init__(
        self,
        *,
        image: Artifact,
        outputs: tuple[Artifact | None, ...],
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name=name, description=description)
        self.image = ArtifactField(required=True)
        self.outputs = (ArtifactField(required=True),)

    def execute(self) -> bytes:
        image = Image.open(
            io.BytesIO(self.image.value)
        ).convert("RGB")
        output = io.BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()
```

Both methods are synchronous, so Jayrun dispatches them through the configured thread executor instead of running CPU processing on FastAPI's event-loop thread. Only one branch executes for each request.

## 6. Build the graph

Each possible route needs its own artifact flow and consumer:

```python
source = Artifact(name="source")
image = Artifact(name="image")
image_to_denoise = Artifact(name="image_to_denoise")
image_to_preserve = Artifact(name="image_to_preserve")

load_image = LoadImage(
    source=source,
    outputs=(image,),
    name="load_image",
)
route_image = RouteImage(
    image=image,
    outputs=(image_to_denoise, image_to_preserve),
    name="route_image",
)
denoise_image = DenoiseImage(
    image=image_to_denoise,
    outputs=(image_to_denoise,),
    name="denoise_image",
)
encode_png = EncodePng(
    image=image_to_preserve,
    outputs=(image_to_preserve,),
    name="encode_png",
)

source_flow = ArtifactFlow(load_image, artifact=source)
image_flow = ArtifactFlow(route_image, artifact=image)
denoise_flow = ArtifactFlow(
    denoise_image,
    artifact=image_to_denoise,
)
preserve_flow = ArtifactFlow(
    encode_png,
    artifact=image_to_preserve,
)

graph = GraphDefinition(
    source_flow,
    image_flow,
    denoise_flow,
    preserve_flow,
    entry_flows=(source_flow,),
)

http_client = HttpClientResource(name="http_client")
graph.bind_resources({load_image.http_client: http_client})
```

Only `source` is supplied by the application. `LoadImage` produces `image`; `RouteImage` activates one branch; and that branch regenerates its artifact as a retained graph exit.

## 7. Join FastAPI's event loop

```python
engine = Engine()


@asynccontextmanager
async def lifespan(_: FastAPI):
    engine.start(loop=asyncio.get_running_loop())
    try:
        yield
    finally:
        await engine.shutdown_async()


app = FastAPI(lifespan=lifespan)
```

FastAPI starts Jayrun with its already-running loop. The application consequently uses `wait_async()` and `shutdown_async()` rather than their blocking counterparts.

The engine shuts down before the FastAPI lifespan exits, which also closes the shared HTTP client.

## 8. Configure, submit, and await one image

The helper receives the input and route decision. It creates fresh artifact and configuration contexts because both belong to one request.

```python
async def run_image(
    source_value: ImageSource,
    *,
    denoise: bool,
) -> Response:
    artifacts = ArtifactContext(graph=graph)
    artifacts.set({source: source_value})

    configs = ConfigContext(graph=graph)
    configs.set({route_image.denoise: denoise})

    context_id = engine.submit(artifacts, configs)

    try:
        snapshot = await engine.wait_async(
            context_id,
            state=ContextState.FINISHED,
            timeout=30,
        )

        if snapshot is None:
            raise HTTPException(status_code=404)
        if snapshot.failure is not None:
            raise HTTPException(
                status_code=422,
                detail=str(snapshot.failure),
            )

        result_artifact = (
            image_to_denoise if denoise else image_to_preserve
        )
        return Response(
            content=snapshot.artifact(result_artifact).value,
            media_type="image/png",
        )
    finally:
        engine.delete(context_id)
```

`wait_async(..., state=ContextState.FINISHED)` expresses the target state directly. There is no polling loop and no repeated manual state check.

The endpoint remains one request-response operation. Waiting suspends only its coroutine while Jayrun performs network and CPU work. The response owns its bytes, so the finalized context can be deleted before FastAPI sends them.

## 9. Expose URL and upload routes

FastAPI parses `denoise=true` or `denoise=false` from the query string and passes it to the context configuration:

```python
@app.post("/images/url")
async def process_url(
    request: ImageUrlRequest,
    denoise: bool = True,
) -> Response:
    return await run_image(
        ImageSource(url=str(request.url)),
        denoise=denoise,
    )


@app.post("/images/upload")
async def process_upload(
    request: Request,
    denoise: bool = True,
) -> Response:
    return await run_image(
        ImageSource(content=await request.body()),
        denoise=denoise,
    )
```

A browser can upload and denoise a file directly:

```javascript
const response = await fetch("/images/upload?denoise=true", {
  method: "POST",
  headers: { "Content-Type": file.type },
  body: file,
});

const processedImage = await response.blob();
```

Set `denoise=false` to select the preservation route. Run the application with:

```bash
uvicorn app:app
```

## What Jayrun adds

| Concern | Owner |
| --- | --- |
| HTTP request and response | FastAPI |
| Shared connection pool | `HttpClientResource` |
| Asynchronous download | `LoadImage` |
| Per-request route choice | `ConfigContext` and `RouteImage` |
| Inactive-branch skipping | Jayrun graph execution |
| Synchronous CPU work | `DenoiseImage` or `EncodePng` |
| Execution and result lifecycle | Jayrun context |
| Non-blocking application wait | `Engine.wait_async()` |
| Startup and cleanup | FastAPI lifespan and Jayrun engine |

The endpoints only translate HTTP values into artifacts and configurations. The graph owns processing order and routing, while the engine owns execution and lifecycle. The same structure works for document conversion, archive inspection, audio processing, and other services that combine asynchronous input with synchronous transformations.

## Production boundaries

This tutorial uses one process-local engine. Run it with one FastAPI worker so the submitting endpoint and Jayrun context registry remain in the same process.

Before accepting arbitrary public URLs, add an allowlist or complete SSRF protection that rejects private, loopback, link-local, and otherwise restricted destinations across DNS resolution and redirects. Enforce request-size limits at the web server as well as in the operator.

For the general routing rules, see {ref}`conditional-routing`. For lifecycle details, see {doc}`Engine and Context Lifecycle <../runtime/engine-and-context-lifecycle>`.

Continue with {doc}`MNIST Inference and Supervised Training <mnist-inference-and-training>` to apply the same graph, resource, and context concepts to CUDA inference and adaptive training.
