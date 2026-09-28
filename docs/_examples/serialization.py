"""Bind complete artifact serializers before confirmation, then register."""
from jayrun import Artifact, ArtifactFlow, BaseSerializer, GraphDefinition, GraphRegistry
from first_graph import Scale


class IntegerBytes(BaseSerializer):
    def serialize(self, value):
        return str(value).encode("ascii")

    def deserialize(self, payload):
        return int(payload.decode("ascii"))


def main():
    source, result = Artifact(name="source"), Artifact(name="result")
    scale = Scale(source=source, outputs=(result,))
    entry = ArtifactFlow(scale, artifact=source)
    graph = GraphDefinition(entry, entry_flows=entry)
    serializer = IntegerBytes()
    graph.bind_serializers({source: serializer, result: serializer})
    graph.confirm()
    registry = GraphRegistry()
    registry.register("scale", graph)
    assert registry.identity_for(graph) == ("scale", "1")
    assert graph.inspect.serializers.complete
    assert serializer.deserialize(serializer.serialize(21)) == 21
    print(registry.identity_for(graph))


if __name__ == "__main__":
    main()
