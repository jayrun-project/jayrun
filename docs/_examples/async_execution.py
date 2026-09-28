"""An application owns the event loop; Jayrun owns its execution lifecycle."""
import asyncio
from jayrun import Artifact, ArtifactField, ArtifactFlow, BaseOperator, Engine, GraphDefinition
from jayrun.context import ContextState


class Fetch(BaseOperator):
    def __init__(self, *, outputs):
        super().__init__()
        self.outputs = (ArtifactField(),)

    async def execute(self):
        await asyncio.sleep(0)  # Replace with application-owned async I/O.
        return "ready"


async def main():
    result = Artifact(name="response")
    graph = GraphDefinition(ArtifactFlow(Fetch(outputs=(result,))))
    graph.confirm()
    engine = Engine()
    engine.start(loop=asyncio.get_running_loop())
    try:
        run = engine.submit(graph)
        await run.wait_async(timeout=5)
        assert run.state is ContextState.FINISHED, run.report.data.failure
        assert run.artifact(result).value == "ready"
        print(run.artifact(result).value)
    finally:
        await engine.shutdown_async(timeout=5)


if __name__ == "__main__":
    asyncio.run(main())
