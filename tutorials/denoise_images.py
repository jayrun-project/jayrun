"""One-process FastAPI service: asynchronous input, routing, shared client, PNG output.

Run from the repository root: uvicorn tutorials.denoise_images:create_app --factory
URL loading is disabled unless create_app(allowed_hosts=(... ,)) opts into known hosts.
"""
from __future__ import annotations

import asyncio
import io
from contextlib import asynccontextmanager
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.testclient import TestClient
from PIL import Image, ImageFilter
from pydantic import BaseModel, HttpUrl

from jayrun import (Artifact, ArtifactContext, ArtifactField, ArtifactFlow,
                    BaseOperator, BaseResource, ConfigContext, ConfigField,
                    Data, Engine, GraphDefinition, ResourceField)
from jayrun.context import ContextState

MAX_IMAGE_BYTES = 2_000_000
MAX_IMAGE_PIXELS = 4_000_000


@dataclass(frozen=True, slots=True)
class ImageSource:
    url: str | None = None
    content: bytes | None = None

    def __post_init__(self) -> None:
        if (self.url is None) == (self.content is None):
            raise ValueError("provide exactly one image source")


class ImageUrlRequest(BaseModel):
    url: HttpUrl


class HttpClientResource(BaseResource):
    requirements = ("httpx",)

    async def setup(self) -> Data:
        return Data(value=httpx.AsyncClient(timeout=10, follow_redirects=False,
                                          trust_env=False))

    async def teardown(self, data: Data) -> None:
        await data.value.aclose()


class LoadImage(BaseOperator):
    def __init__(self, *, source: Artifact, outputs: tuple[Artifact, ...]) -> None:
        super().__init__()
        self.source = ArtifactField(required=True)
        self.http_client = ResourceField(required=True, parallel_safe=True)
        self.outputs = (ArtifactField(required=True),)

    async def execute(self) -> bytes:
        source: ImageSource = self.source.value
        if source.content is not None:
            content = source.content
        else:
            content = bytearray()
            async with self.http_client.value.stream("GET", source.url) as response:
                response.raise_for_status()
                if not response.headers.get("content-type", "").startswith("image/"):
                    raise ValueError("upstream response is not an image")
                async for block in response.aiter_bytes():
                    content.extend(block)
                    if len(content) > MAX_IMAGE_BYTES:
                        raise ValueError("image exceeds the byte limit")
            content = bytes(content)
        if not content or len(content) > MAX_IMAGE_BYTES:
            raise ValueError("image is empty or exceeds the byte limit")
        return content


class RouteImage(BaseOperator):
    def __init__(self, *, image: Artifact, outputs: tuple[Artifact, ...]) -> None:
        super().__init__()
        self.image = ArtifactField(required=True)
        self.denoise = ConfigField(value_type=bool, required=False, default=True)
        self.outputs = (ArtifactField(required=True), ArtifactField(required=True))

    def execute(self) -> tuple[bytes | None, bytes | None]:
        value = self.image.value
        return (value, None) if self.denoise.value else (None, value)


def encode_png(content: bytes, *, denoise: bool) -> bytes:
    with Image.open(io.BytesIO(content)) as source:
        if source.width * source.height > MAX_IMAGE_PIXELS:
            raise ValueError("image exceeds the pixel limit")
        image = source.convert("RGB")
    try:
        if denoise:
            filtered = image.filter(ImageFilter.MedianFilter(size=3))
            image.close()
            image = filtered
        output = io.BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()
    finally:
        image.close()


class EncodeImage(BaseOperator):
    def __init__(self, *, image: Artifact, outputs: tuple[Artifact, ...],
                 denoise: bool) -> None:
        super().__init__()
        self.image = ArtifactField(required=True)
        self.apply_denoising = ConfigField(value_type=bool, required=False, default=denoise)
        self.outputs = (ArtifactField(required=True),)

    def execute(self) -> bytes:
        return encode_png(self.image.value, denoise=self.apply_denoising.value)


def build_graph():
    source, image = Artifact(name="source"), Artifact(name="image")
    denoised, preserved = Artifact(name="denoised"), Artifact(name="preserved")
    load = LoadImage(source=source, outputs=(image,))
    route = RouteImage(image=image, outputs=(denoised, preserved))
    clean = EncodeImage(image=denoised, outputs=(denoised,), denoise=True)
    encode = EncodeImage(image=preserved, outputs=(preserved,), denoise=False)
    entry = ArtifactFlow(load, artifact=source)
    graph = GraphDefinition(entry, ArtifactFlow(route, artifact=image),
                            ArtifactFlow(clean, artifact=denoised),
                            ArtifactFlow(encode, artifact=preserved),
                            entry_flows=(entry,))
    graph.bind_resources({load.http_client: HttpClientResource()}); graph.confirm()
    return graph, source, route, denoised, preserved


def create_app(*, allowed_hosts: tuple[str, ...] = (),
               wait_seconds: float = 30) -> FastAPI:
    """Create a fresh engine for each app lifespan; no import-time runtime state.

    Host matching is a tutorial deployment allowlist, not DNS-rebinding protection.
    Do not expose the URL route to arbitrary public destinations.
    """
    if wait_seconds <= 0:
        raise ValueError("wait_seconds must be positive")
    graph, source, route, denoised, preserved = build_graph()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = Engine()
        engine.start(loop=asyncio.get_running_loop())
        app.state.engine = engine
        try:
            yield
        finally:
            await engine.shutdown_async()

    app = FastAPI(title="Jayrun image processing tutorial", lifespan=lifespan)

    async def process(value: ImageSource, denoise: bool) -> Response:
        artifacts, configs = ArtifactContext(), ConfigContext()
        artifacts.set({source: value})
        configs.set({route.denoise: denoise})
        run = app.state.engine.submit(graph, artifacts, configs)
        try:
            await run.wait_async(timeout=wait_seconds)
        except TimeoutError:
            run.abort()  # A waiting timeout alone does not cancel accepted work.
            await run.wait_async()
            raise HTTPException(504, "image processing timed out") from None
        except asyncio.CancelledError:
            run.abort()
            raise
        if run.state is not ContextState.FINISHED:
            # Internal diagnostics belong in a trusted report, not the HTTP response.
            failure = run.report.data.failure
            raise HTTPException(400, "image processing failed" if failure else run.state.value)
        result = run.artifact(denoised if denoise else preserved).value
        return Response(content=result, media_type="image/png")

    @app.post("/images/upload")
    async def upload(request: Request, denoise: bool = True) -> Response:
        body = bytearray()
        async for block in request.stream():
            body.extend(block)
            if len(body) > MAX_IMAGE_BYTES:
                raise HTTPException(413, "image exceeds the byte limit")
        return await process(ImageSource(content=bytes(body)), denoise)

    @app.post("/images/url")
    async def url(request: ImageUrlRequest, denoise: bool = True) -> Response:
        parsed = urlsplit(str(request.url))
        if parsed.hostname not in allowed_hosts or parsed.username or parsed.password:
            raise HTTPException(403, "URL host is not enabled by this application")
        return await process(ImageSource(url=str(request.url)), denoise)

    return app


def run_demo() -> dict[str, int]:
    source = io.BytesIO()
    with Image.new("RGB", (16, 16), "white") as image:
        image.putpixel((8, 8), (0, 0, 0))
        image.save(source, format="PNG")
    with TestClient(create_app()) as client:
        clean = client.post("/images/upload", content=source.getvalue())
        preserved = client.post("/images/upload?denoise=false", content=source.getvalue())
        invalid = client.post("/images/upload", content=b"not an image")
    assert clean.status_code == preserved.status_code == 200
    assert invalid.status_code == 400
    return {"denoised": clean.status_code, "preserved": preserved.status_code,
            "invalid": invalid.status_code}


if __name__ == "__main__":
    print(run_demo())
