"""A constructed graph can have a property mismatch; confirm rejects it."""
from jayrun import Artifact, ArtifactField, ArtifactFlow, BaseOperator, GraphDefinition
from jayrun.properties import TypeProperty


class Produce(BaseOperator):
    def __init__(self, *, outputs):
        super().__init__()
        self.outputs = (ArtifactField(properties=(TypeProperty(str),)),)

    def execute(self):
        return "text"


class RequireInteger(BaseOperator):
    def __init__(self, *, value):
        super().__init__()
        self.value = ArtifactField(properties=(TypeProperty(int),))
        self.outputs = ()

    def execute(self):
        return ()


def build_graph():
    value = Artifact(name="text supplied where integer is required")
    return GraphDefinition(ArtifactFlow(Produce(outputs=(value,)),
                                        RequireInteger(value=value), artifact=value))


def main():
    graph = build_graph()
    graph.validate()
    try:
        graph.confirm()
    except ValueError:
        print("Property mismatch rejected; supply a compatible producer or conversion.")
    else:
        raise AssertionError("Confirmation must reject a known property mismatch")


if __name__ == "__main__":
    main()
