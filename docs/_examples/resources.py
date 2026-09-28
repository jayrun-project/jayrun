"""Bind a reusable resource and read it through the injected Data value."""
from jayrun import (
    Artifact, ArtifactField, ArtifactFlow, BaseOperator, BaseResource, Data,
    Engine, GraphDefinition, ResourceField,
)
from jayrun.context import ContextState


class Lookup(BaseResource):
    def __init__(self):
        super().__init__()

    def setup(self):
        return Data(value={"answer": 42})

    def teardown(self, data):
        data.value.clear()  # Release application-owned state or close a client.


class Read(BaseOperator):
    def __init__(self, *, outputs):
        super().__init__()
        self.lookup = ResourceField(parallel_safe=True)
        self.outputs = (ArtifactField(),)

    def execute(self):
        return self.lookup.value["answer"]


def main():
    result = Artifact(name="answer")
    read = Read(outputs=(result,))
    graph = GraphDefinition(ArtifactFlow(read))
    graph.bind_resources({read.lookup: Lookup()})
    graph.confirm()
    with Engine() as engine:
        for _ in range(2):
            run = engine.submit(graph)
            run.wait(timeout=5)
            assert run.state is ContextState.FINISHED, run.report.data.failure
            assert run.artifact(result).value == 42
        print(42)


if __name__ == "__main__":
    main()
