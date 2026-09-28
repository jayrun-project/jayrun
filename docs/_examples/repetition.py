"""Consume/regenerate feedback, repeat once per iteration, execute two iterations."""
from jayrun import Artifact, ArtifactContext, ArtifactField, ArtifactFlow, BaseOperator, Engine, GraphDefinition
from jayrun.context import ContextState
from jayrun.settings import ContextSettings


class Increment(BaseOperator):
    def __init__(self, *, value, outputs):
        super().__init__()
        self.value = ArtifactField()
        self.outputs = (ArtifactField(),)

    def execute(self):
        if self.execution.number == 1:
            self.execution.repeat()
        return self.value.value + 1


def main():
    value = Artifact(name="counter")
    step = Increment(value=value, outputs=(value,))
    flow = ArtifactFlow(step, artifact=value)
    graph = GraphDefinition(flow, entry_flows=flow)
    graph.confirm()
    with Engine() as engine:
        run = engine.submit(graph, ArtifactContext({value: 0}),
                            settings=ContextSettings(max_iterations=2, max_repeats=1))
        run.wait(timeout=5)
        assert run.state is ContextState.FINISHED, run.report.data.failure
        assert run.artifact(value).value == 4
        print(4)


if __name__ == "__main__":
    main()
