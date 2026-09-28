"""Regenerate one artifact through two consumers. Prints HELLO!."""
from jayrun import Artifact, ArtifactContext, ArtifactField, ArtifactFlow, BaseOperator, Engine, GraphDefinition
from jayrun.context import ContextState


class AddMark(BaseOperator):
    def __init__(self, *, text, outputs):
        super().__init__()
        self.text = ArtifactField()
        self.outputs = (ArtifactField(),)

    def execute(self):
        return self.text.value + "!"


class Uppercase(BaseOperator):
    def __init__(self, *, text, outputs):
        super().__init__()
        self.text = ArtifactField()
        self.outputs = (ArtifactField(),)

    def execute(self):
        return self.text.value.upper()


def main():
    text = Artifact(name="text")
    mark = AddMark(text=text, outputs=(text,))
    upper = Uppercase(text=text, outputs=(text,))
    flow = ArtifactFlow(mark, upper, artifact=text)
    graph = GraphDefinition(flow, entry_flows=flow)
    graph.confirm()
    with Engine() as engine:
        run = engine.submit(graph, ArtifactContext({text: "hello"}))
        run.wait(timeout=5)
        assert run.state is ContextState.FINISHED, run.report.data.failure
        assert run.artifact(text).value == "HELLO!"
        print(run.artifact(text).value)


if __name__ == "__main__":
    main()
