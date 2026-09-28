"""A Controller submits ordinary registered work. Expected result: 42."""
from jayrun import (
    Artifact, ArtifactField, ArtifactFlow, BaseOperator, ConfigField, Controller,
    Engine, GraphDefinition, GraphRegistry,
)
from jayrun.context import ContextState


class Answer(BaseOperator):
    def __init__(self, *, outputs):
        super().__init__()
        self.outputs = (ArtifactField(),)

    def execute(self):
        return 42


class SubmitWork(BaseOperator):
    def __init__(self, *, graph_key):
        super().__init__()
        self.graph_key = ConfigField(value_type=tuple, required=False, default=graph_key)
        self.outputs = ()

    async def execute(self):
        run = self.runtime.submit(self.graph_key.value)
        await self.runtime.wait_async(run, timeout=5)
        if run.state is not ContextState.FINISHED:
            raise RuntimeError("Child work did not finish successfully")
        self.context.record("child_state", run.state.value)
        self.context.record("child_id", run.context_id)
        return ()


def main():
    result = Artifact(name="answer")
    work = GraphDefinition(ArtifactFlow(Answer(outputs=(result,))))
    work.confirm()
    registry = GraphRegistry()
    registry.register("answer", work)
    controller = GraphDefinition(ArtifactFlow(SubmitWork(graph_key=registry.identity_for(work))))
    controller.confirm()
    registry.register("submit-work", controller)
    with Engine(graph_registry=registry) as engine:
        run = engine.submit(controller, authority=Controller())
        engine.wait(run, timeout=5)
        assert run.state is ContextState.FINISHED, run.report.data.failure
        assert run.records("child_state")[0].value == ContextState.FINISHED.value
        print(run.records("child_state")[0].value)


if __name__ == "__main__":
    main()
