```{eval-rst}
.. meta::
   :description: Build a FastAPI image-processing workflow with Jayrun, reusable async HTTP resources, per-request configuration and synchronous image operators.
```

(tutorial-denoise-images-with-fastapi)=
# Denoise Images with FastAPI

Build an image request around a confirmed graph, compare two conditional routes, and inspect an invalid request. You should know basic Python and HTTP request/response concepts; FastAPI familiarity helps. Pillow performs the image operation, while Jayrun manages execution and the reusable HTTP client.

## Run it

Follow [tutorial setup](index.md#prepare-your-environment), then run from the repository root:

```bash
python -m tutorials.denoise_images
uvicorn tutorials.denoise_images:create_app --factory
```

Open `tutorials/02_denoise_images.ipynb` for the guided lesson. The Python snippets below are consecutive notebook cells: run them in Jupyter with top-level `await`. For a terminal run, use the module command above.

## 1. Trace the route

**ImageSource → LoadImage → RouteImage → EncodeImage → PNG response**. RouteImage has two distinct output artifacts. One carries image bytes and the other receives None, which skips its consumer. The graph declaration stays the same for both requests. The request's ConfigContext chooses the route.

<!-- notebook: 02_denoise_images.ipynb#inspect-builder -->
```python
import asyncio
import inspect
import io
from PIL import Image
from IPython.display import display
from fastapi.testclient import TestClient
from tutorials import denoise_images as lesson

print(inspect.getsource(lesson.build_graph))
```

## 2. Make the difference visible

Create a white image with a black pixel. The median filter should remove that isolated pixel; the preserving route should keep it. We send raw PNG bytes, not multipart form data. The same requests work against Uvicorn at /images/upload.

<!-- notebook: 02_denoise_images.ipynb#prepare-image -->
```python
buffer = io.BytesIO()
with Image.new("RGB", (16, 16), "white") as image:
    image.putpixel((8, 8), (0, 0, 0))
    image.save(buffer, format="PNG")
source_png = buffer.getvalue()
with Image.open(io.BytesIO(source_png)) as image:
    display(image.resize((160, 160), Image.Resampling.NEAREST))
```

## 3. Exercise the application lifespan

TestClient's context manager starts and closes the app lifespan, including the Engine. Calls run in a worker thread so they do not nest a synchronous service demonstration inside Jupyter's loop. Each request gets its own run; both responses should be HTTP 200 with PNG content.

<!-- notebook: 02_denoise_images.ipynb#route-images -->
```python
def compare_routes():
    with TestClient(lesson.create_app()) as client:
        clean = client.post("/images/upload?denoise=true", content=source_png)
        preserved = client.post("/images/upload?denoise=false", content=source_png)
    assert clean.status_code == preserved.status_code == 200
    assert clean.headers["content-type"] == "image/png"
    return clean.content, preserved.content

clean_png, preserved_png = await asyncio.to_thread(compare_routes)
for label, content in (("Preserved", preserved_png), ("Denoised", clean_png)):
    with Image.open(io.BytesIO(content)) as image:
        print(label, "center pixel:", image.getpixel((8, 8)))
        display(image.resize((160, 160), Image.Resampling.NEAREST))
with Image.open(io.BytesIO(clean_png)) as image:
    assert image.getpixel((8, 8)) == (255, 255, 255)
with Image.open(io.BytesIO(preserved_png)) as image:
    assert image.getpixel((8, 8)) == (0, 0, 0)
```

## 4. Inspect a controlled failure

An invalid image should return 400. A URL is refused with 403 unless its host is explicitly allowed. These are application policies. A wait timeout is handled differently: the application requests abort, drains the run, then returns 504; waiting alone does not cancel accepted work.

<!-- notebook: 02_denoise_images.ipynb#invalid-input -->
```python
def check_invalid_requests():
    with TestClient(lesson.create_app()) as client:
        invalid = client.post("/images/upload", content=b"not an image")
        disabled = client.post("/images/url", json={"url": "http://127.0.0.1/image.png"})
        return invalid.status_code, disabled.status_code

statuses = await asyncio.to_thread(check_invalid_requests)
print("Invalid image / disabled URL:", statuses)
assert statuses == (400, 403)
```

## Try it yourself

Move the black pixel in the preparation cell and update the inspected coordinates and pixel assertions before rerunning the comparison. You can also add a larger black patch and inspect it separately. A median filter removes isolated noise; it need not remove a larger region. Keep both HTTP status and decoded pixels in your inspection.

Serve with one ASGI worker. Public exposure needs application authentication and upload limits. The host allowlist is not complete SSRF/DNS-rebinding protection; redirects are not followed. The HTTP resource is used for URL loading, while these offline requests exercise the byte-upload path.

## Send a request to Uvicorn

With the service running and a local PNG saved as `input.png`, send its raw bytes:

```bash
curl --fail --data-binary @input.png -H "Content-Type: image/png" \
  "http://127.0.0.1:8000/images/upload?denoise=true" --output cleaned.png
```

Change the query to `denoise=false` to preserve the image. Inspect both PNGs, not only the status code.

## Application lifecycle

The Engine starts on FastAPI's event loop in the lifespan and is awaited during shutdown. Synchronous image operators run through Jayrun's executor, while endpoints await `wait_async()`. The canonical application below shows timeout-to-abort drainage and cancellation handling.

## Read the canonical implementation

The complete [denoise_images.py](https://github.com/jayrun-project/jayrun/blob/main/tutorials/denoise_images.py) supplies the operators and application helpers used above. This excerpt shows application assembly:

```{literalinclude} ../../tutorials/denoise_images.py
:language: python
:pyobject: create_app
```

Continue with [the tutorial collection](index.md) or [supported behavior and limitations](../reference/limits.md).
