"""Publish None on the inactive route. Expected: (11, None), (None, 11)."""
from jayrun import Artifact, ArtifactField, ArtifactFlow, BaseOperator, ConfigField, Engine, GraphDefinition
from jayrun.context import ContextState
from jayrun.properties import TypeProperty


class Route(BaseOperator):
    def __init__(self, *, choose_left, outputs):
        super().__init__()
        self.choose_left = ConfigField(value_type=bool, required=False, default=choose_left)
        self.outputs = (ArtifactField(properties=(TypeProperty(int),)),
                        ArtifactField(properties=(TypeProperty(int),)))

    def execute(self):
        return (10, None) if self.choose_left.value else (None, 10)


class Consume(BaseOperator):
    def __init__(self, *, value, outputs):
        super().__init__()
        # Optional binding still skips if a CONNECTED input value is None.
        self.value = ArtifactField(required=False, properties=(TypeProperty(int),))
        self.outputs = (ArtifactField(properties=(TypeProperty(int),)),)

    def execute(self):
        self.context.record("branch", self.value.value)
        return self.value.value + 1


def build_graph(choose_left=True):
    left, right, a, b = (Artifact(name=n) for n in ("left", "right", "left result", "right result"))
    route = Route(choose_left=choose_left, outputs=(left, right))
    first = Consume(value=left, outputs=(a,))
    second = Consume(value=right, outputs=(b,))
    graph = GraphDefinition(ArtifactFlow(route, first, artifact=left),
                            ArtifactFlow(route, second, artifact=right))
    graph.confirm()
    return graph, a, b


def main():
    for choose_left in (True, False):
        graph, a, b = build_graph(choose_left)
        with Engine() as engine:
            run = engine.submit(graph)
            run.wait(timeout=5)
            assert run.state is ContextState.FINISHED, run.report.data.failure
            values = (run.artifact(a).value, run.artifact(b).value)
            assert values == ((11, None) if choose_left else (None, 11))
            skipped = [e for e in run.report.data.executions if e.skip_reason == "missing_input"]
            assert len(skipped) == 1
            assert len(run.records("branch")) == 1
            print(values)


if __name__ == "__main__":
    main()
