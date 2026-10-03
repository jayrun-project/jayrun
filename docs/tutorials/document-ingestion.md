```{eval-rst}
.. meta::
   :description: Build a controllable Python document-ingestion service around Jayrun with bounded admission, inspection, review, cancellation and transactional publication.
```

(tutorial-document-ingestion)=
# Controllable Document Ingestion

Submit a background document job, inspect a review pause, resume it, and search published chunks. You should know basic Python and HTTP. This example composes a Jayrun graph with application-owned job records and SQLite transactions; its hashing encoder provides lexical retrieval without a model download.

## Run it

Follow [tutorial setup](index.md#prepare-your-environment), then run from the repository root:

```bash
python -m tutorials.document_ingestion
uvicorn tutorials.document_ingestion:create_app --factory
```

Open `tutorials/05_document_ingestion.ipynb` for the guided lesson. The Python snippets below are consecutive notebook cells: run them in Jupyter with top-level `await`. For a terminal run, use the module command above.

## 1. Follow the document

**DocumentWork → ParseDocument → EmbedDocument → PublishDocument**. Parsing creates chunks and can pause for review. A shared read-only encoder produces lexical vectors. The index resource serializes publication in a transaction. The same document artifact carries successive values; publication ends with a receipt.

<!-- notebook: 05_document_ingestion.ipynb#inspect-builder -->
```python
import asyncio
import inspect
import tempfile
from fastapi.testclient import TestClient
from tutorials import document_ingestion as lesson

print(inspect.getsource(lesson.build_graph))
```

## 2. Pause, review, and publish

POST /jobs returns 202 and a content-derived job_id. Waiting for PAUSED should reveal only the parsed stage, and search should still be empty. Resume allows embedding and publication. Terminal wait also waits for the application's finalization task. The test client calls the real application, including its lifespan.

<!-- notebook: 05_document_ingestion.ipynb#review-and-publish -->
```python
def review_document():
    with TestClient(lesson.create_app()) as client:
        submitted = client.post("/jobs", json={"text": "Jayrun shares resources and manages execution.",
                                               "review": True})
        assert submitted.status_code == 202
        job_id = submitted.json()["job_id"]
        paused = client.post(f"/jobs/{job_id}/wait?paused=true").json()
        assert paused["state"] == "paused" and paused["stages"] == ["parsed"]
        before = client.get("/search", params={"q": "resources"}).json()
        assert before == []
        client.post(f"/jobs/{job_id}/resume").raise_for_status()
        finished = client.post(f"/jobs/{job_id}/wait").json()
        matches = client.get("/search", params={"q": "resources"}).json()
        assert finished["state"] == "finished" and finished["published"] and matches
        return {"paused_stages": paused["stages"], "final_stages": finished["stages"],
                "state": finished["state"], "published": finished["published"],
                "matches": len(matches)}

review = await asyncio.to_thread(review_document)
print(review)
assert review["final_stages"] == ["parsed", "embedded", "published"]
```

## 3. See the application's capacity policy

Keep one job paused in an app with max_active=1. Repeating the same content returns the existing job even when capacity is full. New content receives 429. Cancel drains the paused run without publishing it; delete removes the terminal job record and indexed content. Count limits are application admission policies, not global memory bounds.

<!-- notebook: 05_document_ingestion.ipynb#capacity-and-cancel -->
```python
def inspect_admission():
    with TestClient(lesson.create_app(max_active=1, max_history=2)) as client:
        body = {"text": "review this document", "review": True}
        first = client.post("/jobs", json=body)
        first.raise_for_status()
        job_id = first.json()["job_id"]
        assert client.post(f"/jobs/{job_id}/wait?paused=true").json()["state"] == "paused"
        duplicate = client.post("/jobs", json=body)
        blocked = client.post("/jobs", json={"text": "different document"})
        assert duplicate.json()["job_id"] == job_id and blocked.status_code == 429
        cancelled = client.post(f"/jobs/{job_id}/cancel").json()
        assert cancelled["state"] == "aborted" and not cancelled["published"]
        assert client.delete(f"/jobs/{job_id}").json() == {"deleted": True}
        return {"duplicate": duplicate.status_code, "new_job": blocked.status_code,
                "cancelled": cancelled["state"]}

admission = await asyncio.to_thread(inspect_admission)
print(admission)
```

## 4. Read a completed job after restart

Passing storage selects an application directory. We close one lifespan and open another against the same temporary directory; the completed job and published chunks remain readable. A stored accepted job with no live owner instead becomes interrupted. This is durable application data, not automatic recovery of a live ContextRun.

<!-- notebook: 05_document_ingestion.ipynb#restart -->
```python
def inspect_restart():
    with tempfile.TemporaryDirectory() as storage:
        with TestClient(lesson.create_app(storage=storage)) as client:
            response = client.post("/jobs", json={"text": "persistent resources"})
            response.raise_for_status()
            job_id = response.json()["job_id"]
            assert client.post(f"/jobs/{job_id}/wait").json()["published"]
        with TestClient(lesson.create_app(storage=storage)) as client:
            stored = client.get(f"/jobs/{job_id}").json()
            assert stored["state"] == "finished" and stored["published"]
            return {"state": stored["state"], "published": stored["published"]}

restarted = await asyncio.to_thread(inspect_restart)
print(restarted)
```

## Try it yourself

Use kind="html" and include a script element. Inspect which text reaches search. Then cancel at the review boundary and verify no chunks are published. Cancellation racing a committed transaction cannot undo that external effect; inspect publication separately from execution outcome.

Use one ASGI worker. Add authentication, per-user job authorization, and an application storage/retention policy before exposure. This example is not a distributed transactional queue. Waiting with a timeout does not cancel a job.

## Send requests to Uvicorn

Submit content for review:

```bash
curl --fail -X POST http://127.0.0.1:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"text":"Jayrun shares resources","review":true}'
```

Copy `job_id` from the 202 response. Replace `JOB_ID` below with that identifier:

```bash
curl --fail -X POST "http://127.0.0.1:8000/jobs/JOB_ID/wait?paused=true"
curl --fail -X POST "http://127.0.0.1:8000/jobs/JOB_ID/resume"
curl --fail -X POST "http://127.0.0.1:8000/jobs/JOB_ID/wait"
curl --fail "http://127.0.0.1:8000/search?q=resources"
```

The review response has `state="paused"` and stages `["parsed"]`. The terminal response has `state="finished"`, a true publication receipt, and stages `["parsed", "embedded", "published"]`. State immediately after submission or resume can vary; use the wait endpoints for these checkpoints.

## Publication and retention

Index rows and their receipt commit together; insertion failure rolls back the transaction. Cancellation before publication leaves no chunks, but cannot undo a commit that already happened. Short-lived connections are explicitly closed. The default service admits four active jobs and retains 1,000 job rows/handles; history exhaustion returns 507. Delete terminal jobs deliberately to free retained capacity. Shutdown aborts live jobs and drains both the Engine and application finalizers.

## Read the canonical implementation

The complete [document_ingestion.py](https://github.com/jayrun-project/jayrun/blob/main/tutorials/document_ingestion.py) supplies the operators and application helpers used above. This excerpt shows graph wiring:

```{literalinclude} ../../tutorials/document_ingestion.py
:language: python
:pyobject: build_graph
```

Continue with [the tutorial collection](index.md) or [supported behavior and limitations](../reference/limits.md).
