(tutorial-denoise-images-with-fastapi)=
# Denoise Images with FastAPI

A request supplies image bytes or an explicitly allowed URL. Jayrun shares an asynchronous
HTTP client, routes from per-request configuration, runs synchronous image work outside
the application event loop, and retains the selected PNG result.

## Run it

```bash
python -m tutorials.denoise_images
uvicorn tutorials.denoise_images:create_app --factory
```

Use `tutorials/02_denoise_images.ipynb` for an executable client demonstration. Install
`tutorials/requirements.txt` in a suitable environment; no AI model is needed.

## Keep the application small

The graph uses a loader, a router, and the same PNG operator for each route. Pillow's
median filter performs the image transformation. Returning
`None` disables one declared route for that context; it does not remove the declaration.

```{literalinclude} ../../tutorials/denoise_images.py
:language: python
:pyobject: build_graph
```

## Own the runtime in the FastAPI lifespan

A new lifespan creates a fresh engine on FastAPI's loop and awaits engine shutdown.
Endpoints use `wait_async()`. Invalid image content becomes a controlled HTTP 400.
Inspect `run.report.data.failure` for the execution failure.
A wait timeout explicitly aborts the accepted run and drains it; timeout by itself is
not cancellation. In-flight Python/native work is not instantly preempted, so the drain
can exceed the waiting timeout. A cancelled coroutine requests abort; shutdown owns drainage.

```{literalinclude} ../../tutorials/denoise_images.py
:language: python
:pyobject: create_app
```

## Verify and deploy deliberately

Try both `denoise=true` and `denoise=false` in the notebook client. The response is PNG bytes in either case; the difference is which declared route processes the image. Invalid content returns HTTP 400, and an execution wait timeout returns HTTP 504 after the run drains.

Use one ASGI worker. URL loading is disabled by default. An explicit known-host allowlist
is a deployment restriction, not complete DNS-rebinding/SSRF protection. Redirects are not
followed. Upload limits also belong at the proxy/server boundary; this lesson does not
provide authentication or multi-tenant isolation.

## Canonical source

The complete runnable implementation is [tutorials/denoise_images.py](https://github.com/jayrun-project/jayrun/blob/main/tutorials/denoise_images.py).
Use {doc}`the tutorial index <index>` for all notebooks and their execution requirements.
