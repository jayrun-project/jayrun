"""Copy a list into two independent branches, then join their results: 16."""
from jayrun import (
    Artifact, ArtifactContext, ArtifactField, ArtifactFlow, BaseOperator,
    ConfigField, Engine, GraphDefinition,
)
from jayrun.context import ContextState
from jayrun.properties import TypeProperty


class Splitter(BaseOperator):
    def __init__(self, *, source, outputs):
        super().__init__()
        self.source = ArtifactField(properties=(TypeProperty(list),))
        self.outputs = (ArtifactField(properties=(TypeProperty(list),)),
                        ArtifactField(properties=(TypeProperty(list),)))

    def execute(self):
        # Distinct artifacts alone do not copy Python objects.
        return list(self.source.value), list(self.source.value)


class AppendAndSum(BaseOperator):
    def __init__(self, *, source, number, outputs):
        super().__init__()
        self.source = ArtifactField(properties=(TypeProperty(list),))
        self.number = ConfigField(value_type=int, required=False, default=number)
        self.outputs = (ArtifactField(properties=(TypeProperty(int),)),)

    def execute(self):
        self.source.value.append(self.number.value)
        return sum(self.source.value)


class Join(BaseOperator):
    def __init__(self, *, left, right, outputs):
        super().__init__()
        self.left = ArtifactField(properties=(TypeProperty(int),))
        self.right = ArtifactField(properties=(TypeProperty(int),))
        self.outputs = (ArtifactField(properties=(TypeProperty(int),)),)

    def execute(self):
        return self.left.value + self.right.value


def build_graph():
    source, left, right, left_sum, right_sum, total = (
        Artifact(name=name) for name in
        ("source", "left", "right", "left sum", "right sum", "total")
    )
    split = Splitter(source=source, outputs=(left, right))
    a = AppendAndSum(source=left, number=3, outputs=(left_sum,))
    b = AppendAndSum(source=right, number=7, outputs=(right_sum,))
    join = Join(left=left_sum, right=right_sum, outputs=(total,))
    entry = ArtifactFlow(split, artifact=source)
    graph = GraphDefinition(
        entry, ArtifactFlow(a, artifact=left), ArtifactFlow(b, artifact=right),
        ArtifactFlow(join, artifact=left_sum), ArtifactFlow(join, artifact=right_sum),
        entry_flows=entry,
    )
    graph.confirm()
    return graph, source, total


def main():
    graph, source, total = build_graph()
    original = [1, 2]
    with Engine() as engine:
        run = engine.submit(graph, ArtifactContext({source: original}))
        run.wait(timeout=5)
        assert run.state is ContextState.FINISHED, run.report.data.failure
        assert run.artifact(total).value == 16
        assert original == [1, 2]
        print(run.artifact(total).value)


if __name__ == "__main__":
    main()
