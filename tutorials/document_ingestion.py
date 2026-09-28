"""Bounded, controllable text/HTML ingestion with application-owned SQLite publication.

The deterministic hashing encoder is lexical, not a learned semantic embedding model.
Use one ASGI worker. A durable job row is not automatic crash recovery for a ContextRun.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import sqlite3
import tempfile
from contextlib import asynccontextmanager, closing
from dataclasses import dataclass, replace
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from jayrun import (Artifact, ArtifactContext, ArtifactField, ArtifactFlow, BaseOperator,
                    BaseResource, ConfigContext, ConfigField, Data, Engine,
                    GraphDefinition, ResourceField)
from jayrun.context import ContextState
from jayrun.settings import ArtifactPolicy, ContextSettings


class DocumentRequest(BaseModel):
    text: str = Field(min_length=1, max_length=100_000)
    kind: Literal["text", "html"] = "text"
    review: bool = False


@dataclass(frozen=True, slots=True)
class DocumentWork:
    job_id: str
    text: str
    kind: str
    chunks: tuple[str, ...] = ()
    vectors: tuple[tuple[float, ...], ...] = ()


class PlainText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


@dataclass(frozen=True, slots=True)
class HashEncoder:
    dimensions: int = 256

    def encode(self, text: str) -> tuple[float, ...]:
        vector = [0.0] * self.dimensions
        for token in re.findall(r"\w+", text.lower()):
            index = int.from_bytes(hashlib.sha256(token.encode()).digest()[:4]) % self.dimensions
            vector[index] += 1.0
        length = math.sqrt(sum(value * value for value in vector)) or 1.0
        return tuple(value / length for value in vector)


class JobStore:
    """Application storage: each operation owns a short-lived SQLite connection."""
    def __init__(self, path: str) -> None:
        self.path = path

    def initialize(self) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY, state TEXT NOT NULL,
                    chunks INTEGER NOT NULL DEFAULT 0, published INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS chunks (
                    job_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
                    text TEXT NOT NULL, vector TEXT NOT NULL,
                    PRIMARY KEY(job_id, ordinal));
            """)
            # An interrupted run must be explicitly resubmitted; do not invent recovery.
            db.execute("UPDATE jobs SET state='interrupted' WHERE state='accepted'")

    def get(self, job_id: str) -> dict[str, object] | None:
        with closing(sqlite3.connect(self.path)) as db, db:
            row = db.execute("SELECT job_id,state,chunks,published FROM jobs WHERE job_id=?",
                             (job_id,)).fetchone()
        return None if row is None else dict(zip(("job_id", "state", "chunks", "published"), row))

    def admit(self, job_id: str, limit: int) -> bool:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] >= limit:
                return False
            db.execute("INSERT INTO jobs(job_id,state) VALUES(?, 'accepted')", (job_id,))
        return True

    def publish(self, work: DocumentWork) -> None:
        # Both the visible index and its publication receipt commit together.
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DELETE FROM chunks WHERE job_id=?", (work.job_id,))
            db.executemany("INSERT INTO chunks VALUES(?,?,?,?)",
                           ((work.job_id, i, text, json.dumps(vector))
                            for i, (text, vector) in enumerate(zip(work.chunks, work.vectors, strict=True))))
            db.execute("UPDATE jobs SET published=1,chunks=? WHERE job_id=?",
                       (len(work.chunks), work.job_id))

    def finish(self, job_id: str, state: str) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE jobs SET state=? WHERE job_id=?", (state, job_id))

    def delete(self, job_id: str) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DELETE FROM chunks WHERE job_id=?", (job_id,))
            db.execute("DELETE FROM jobs WHERE job_id=?", (job_id,))

    def search(self, query: str) -> list[dict[str, object]]:
        query_vector = HashEncoder().encode(query)
        with closing(sqlite3.connect(self.path)) as db, db:
            rows = db.execute("SELECT job_id,ordinal,text,vector FROM chunks").fetchall()
        ranked = [(sum(a*b for a, b in zip(query_vector, json.loads(vector))),
                   job_id, ordinal, text) for job_id, ordinal, text, vector in rows]
        return [{"score": score, "job_id": job_id, "chunk": ordinal, "text": text}
                for score, job_id, ordinal, text in sorted(ranked, reverse=True)[:5] if score > 0]


class EncoderResource(BaseResource):
    def setup(self) -> Data:
        return Data(value=HashEncoder())

    def teardown(self, data: Data) -> None:
        pass  # An immutable Python encoder owns no external handle.


class IndexResource(BaseResource):
    def __init__(self, *, path: str) -> None:
        super().__init__()
        self.path = ConfigField(value_type=str, required=False, default=path)

    def setup(self) -> Data:
        return Data(value=JobStore(self.path.value))

    def teardown(self, data: Data) -> None:
        pass  # Each operation closes its own SQLite connection.


class ParseDocument(BaseOperator):
    def __init__(self, *, document: Artifact, outputs: tuple[Artifact, ...]) -> None:
        super().__init__()
        self.document = ArtifactField(required=True)
        self.review = ConfigField(value_type=bool, required=False, default=False)
        self.outputs = (ArtifactField(required=True),)

    def execute(self) -> DocumentWork:
        work: DocumentWork = self.document.value
        text = work.text
        if work.kind == "html":
            parser = PlainText()
            parser.feed(text)
            parser.close()
            text = " ".join(parser.parts)
        words = text.split()
        if not words:
            raise ValueError("document contains no indexable text")
        chunks = tuple(" ".join(words[i:i + 64]) for i in range(0, len(words), 64))
        self.context.record("chunks", len(chunks))
        self.context.record("stage", "parsed")
        if self.review.value:
            self.context.pause(None)
        return replace(work, text="", chunks=chunks)


class EmbedDocument(BaseOperator):
    def __init__(self, *, document: Artifact, outputs: tuple[Artifact, ...]) -> None:
        super().__init__()
        self.document = ArtifactField(required=True)
        self.encoder = ResourceField(required=True, parallel_safe=True)
        self.outputs = (ArtifactField(required=True),)

    def execute(self) -> DocumentWork:
        work: DocumentWork = self.document.value
        vectors = tuple(self.encoder.value.encode(text) for text in work.chunks)
        self.context.record("stage", "embedded")
        return replace(work, vectors=vectors)


class PublishDocument(BaseOperator):
    def __init__(self, *, document: Artifact, outputs: tuple[Artifact, ...]) -> None:
        super().__init__()
        self.document = ArtifactField(required=True)
        self.index = ResourceField(required=True, parallel_safe=False)
        self.outputs = (ArtifactField(required=True),)

    def execute(self) -> dict[str, object]:
        work: DocumentWork = self.document.value
        self.index.value.publish(work)
        self.context.record("stage", "published")
        return {"job_id": work.job_id, "chunks": len(work.chunks)}


def build_graph(path: str):
    document = Artifact(name="document")
    parse = ParseDocument(document=document, outputs=(document,))
    embed = EmbedDocument(document=document, outputs=(document,))
    publish = PublishDocument(document=document, outputs=(document,))
    flow = ArtifactFlow(parse, embed, publish, artifact=document)
    graph = GraphDefinition(flow, entry_flows=(flow,))
    graph.bind_resources({embed.encoder: EncoderResource(), publish.index: IndexResource(path=path)}); graph.confirm()
    return graph, document, parse


def create_app(*, storage: str | Path | None = None, max_active: int = 4,
               max_history: int = 1000) -> FastAPI:
    if max_active < 1 or max_history < max_active:
        raise ValueError("require 1 <= max_active <= max_history")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        with tempfile.TemporaryDirectory(prefix="jayrun-ingestion-") as temporary:
            folder = Path(storage) if storage is not None else Path(temporary)
            folder.mkdir(parents=True, exist_ok=True)
            store = JobStore(str(folder / "documents.sqlite3"))
            await asyncio.to_thread(store.initialize)
            graph, document, parse = build_graph(store.path)
            engine = Engine()
            engine.start(loop=asyncio.get_running_loop())
            app.state.engine, app.state.store = engine, store
            app.state.graph, app.state.document, app.state.parse = graph, document, parse
            app.state.runs, app.state.watchers = {}, {}
            app.state.admission = asyncio.Lock()
            try:
                yield
            finally:
                for run in app.state.runs.values():
                    if not run.state.is_terminal:
                        run.abort()
                await engine.shutdown_async()
                await asyncio.gather(*app.state.watchers.values(), return_exceptions=True)

    app = FastAPI(title="Jayrun document ingestion tutorial", lifespan=lifespan)

    async def status(job_id: str) -> dict[str, object]:
        value = await asyncio.to_thread(app.state.store.get, job_id)
        if value is None:
            raise HTTPException(404, "job not found")
        run = app.state.runs.get(job_id)
        if run is not None:
            value["state"] = run.state.value
            value["stages"] = [record.value for record in run.records("stage")]
        return value

    @app.post("/jobs", status_code=202)
    async def submit(request: DocumentRequest) -> dict[str, object]:
        digest = hashlib.sha256((request.kind + "\0" + request.text).encode()).hexdigest()
        async with app.state.admission:
            prior = await asyncio.to_thread(app.state.store.get, digest)
            if prior is not None:
                return await status(digest)
            if sum(not run.state.is_terminal for run in app.state.runs.values()) >= max_active:
                raise HTTPException(429, "active job capacity exhausted", headers={"Retry-After": "1"})
            if not await asyncio.to_thread(app.state.store.admit, digest, max_history):
                raise HTTPException(507, "history capacity exhausted; delete a terminal job")
            inputs, configs = ArtifactContext(), ConfigContext()
            inputs.set({app.state.document: DocumentWork(digest, request.text, request.kind)})
            configs.set({app.state.parse.review: request.review})
            try:
                run = app.state.engine.submit(app.state.graph, inputs, configs,
                    settings=ContextSettings(record_history_limit=4,
                        artifact_policy=ArtifactPolicy(release_entry_artifacts=True)))
            except Exception:
                await asyncio.to_thread(app.state.store.delete, digest)
                raise
            app.state.runs[digest] = run

            async def finalize() -> None:
                await run.wait_async()
                await asyncio.to_thread(app.state.store.finish, digest, run.state.value)

            app.state.watchers[digest] = asyncio.create_task(finalize())
        return await status(digest)

    @app.get("/jobs/{job_id}")
    async def get_job(job_id: str) -> dict[str, object]:
        return await status(job_id)

    @app.post("/jobs/{job_id}/wait")
    async def wait_job(job_id: str, paused: bool = False) -> dict[str, object]:
        await status(job_id)
        run = app.state.runs.get(job_id)
        if run is not None:
            try:
                await run.wait_async(ContextState.PAUSED if paused else None, timeout=30)
            except TimeoutError:
                raise HTTPException(504, "waiting timed out; the job was not cancelled") from None
            if run.state.is_terminal:
                await app.state.watchers[job_id]
        return await status(job_id)

    @app.post("/jobs/{job_id}/resume")
    async def resume(job_id: str) -> dict[str, object]:
        await status(job_id)
        run = app.state.runs.get(job_id)
        if run is None or run.state is not ContextState.PAUSED:
            raise HTTPException(409, "job is not paused in this engine")
        run.resume()
        return await status(job_id)

    @app.post("/jobs/{job_id}/cancel")
    async def cancel(job_id: str) -> dict[str, object]:
        await status(job_id)
        run = app.state.runs.get(job_id)
        if run is not None:
            run.abort()
            await run.wait_async(timeout=30)
            await app.state.watchers[job_id]
        return await status(job_id)

    @app.delete("/jobs/{job_id}")
    async def delete(job_id: str) -> dict[str, bool]:
        async with app.state.admission:
            await status(job_id)
            run = app.state.runs.get(job_id)
            if run is not None:
                if not run.state.is_terminal:
                    raise HTTPException(409, "cancel or finish the job before deletion")
                await app.state.watchers[job_id]
            await asyncio.to_thread(app.state.store.delete, job_id)
            app.state.runs.pop(job_id, None)
            app.state.watchers.pop(job_id, None)
        return {"deleted": True}

    @app.get("/search")
    async def search(q: str) -> list[dict[str, object]]:
        if not q.strip() or len(q) > 1000:
            raise HTTPException(422, "provide a query of 1 to 1000 characters")
        return await asyncio.to_thread(app.state.store.search, q)

    return app


def run_demo() -> dict[str, object]:
    with TestClient(create_app()) as client:
        job = client.post("/jobs", json={"text": "Jayrun shares resources and manages execution.",
                                          "review": True}).json()
        job_id = job["job_id"]
        assert client.post(f"/jobs/{job_id}/wait?paused=true").json()["state"] == "paused"
        client.post(f"/jobs/{job_id}/resume").raise_for_status()
        finished = client.post(f"/jobs/{job_id}/wait").json()
        matches = client.get("/search", params={"q": "resources"}).json()
        assert finished["state"] == "finished" and matches
        return {"state": finished["state"], "published": bool(finished["published"]),
                "matches": len(matches), "stages": finished["stages"]}


if __name__ == "__main__":
    print(run_demo())
