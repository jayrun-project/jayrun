"""Run with python docs/_examples/first_graph.py. Expected result: 21."""
from jayrun import (
    Artifact, ArtifactContext, ArtifactField, ArtifactFlow, BaseOperator,
    ConfigContext, ConfigField, Engine, GraphDefinition,
)
from jayrun.context import ContextState


class Scale(BaseOperator):
    def __init__(self, *, source, outputs):
        super().__init__()
        self.source = ArtifactField()
        self.factor = ConfigField(value_type=int)
        self.outputs = (ArtifactField(),)

    def execute(self):
        result = self.source.value * self.factor.value
        self.context.record("scaled", result)
        return result


def build_graph():
    source, result = Artifact(name="source"), Artifact(name="result")
    scale = Scale(source=source, outputs=(result,))
    flow = ArtifactFlow(scale, artifact=source)
    graph = GraphDefinition(flow, entry_flows=flow)
    assert graph.validate().valid
    graph.confirm()
    return graph, source, result, scale


def main():
    graph, source, result, scale = build_graph()
    with Engine() as engine:
        run = engine.submit(graph, ArtifactContext({source: 7}),
                            ConfigContext({scale.factor: 3}))
        run.wait(timeout=5)
        assert run.state is ContextState.FINISHED, run.report.data.failure
        assert run.artifact(result).value == 21
        assert run.records("scaled")[-1].value == 21
        print(run.artifact(result).value)


if __name__ == "__main__":
    main()
