"""One declaration, fresh data/configuration per run, reusable calibration resource."""
from jayrun import (
    Artifact, ArtifactContext, ArtifactField, ArtifactFlow, BaseOperator,
    BaseResource, ConfigContext, ConfigField, Data, Engine, GraphDefinition,
    ResourceField,
)
from jayrun.context import ContextState
from jayrun.properties import TypeProperty


class Calibration(BaseResource):
    def __init__(self) -> None:
        super().__init__()
        self.offset = ConfigField(value_type=int)

    def setup(self) -> Data:
        self.context.record("calibration_loaded", self.offset.value)
        return Data(value={"offset": self.offset.value})

    def teardown(self, data: Data) -> None:
        data.value.clear()


class Adjust(BaseOperator):
    def __init__(self, *, sample: Artifact, outputs: tuple[Artifact, ...]) -> None:
        super().__init__()
        self.sample = ArtifactField(properties=(TypeProperty(int),))
        self.calibration = ResourceField(parallel_safe=True)
        self.outputs = (ArtifactField(properties=(TypeProperty(int),)),)

    def execute(self) -> int:
        return self.sample.value + self.calibration.value["offset"]


class Scale(BaseOperator):
    def __init__(self, *, adjusted: Artifact, outputs: tuple[Artifact, ...]) -> None:
        super().__init__()
        self.adjusted = ArtifactField(properties=(TypeProperty(int),))
        self.factor = ConfigField(value_type=int)
        self.outputs = (ArtifactField(properties=(TypeProperty(int),)),)

    def execute(self) -> int:
        result = self.adjusted.value * self.factor.value
        self.context.record("result", result)
        return result


def build_graph() -> tuple[GraphDefinition, Artifact, Artifact, Calibration, Scale]:
    sample = Artifact(name="sample")
    adjusted = Artifact(name="adjusted")
    result = Artifact(name="result")
    calibration = Calibration()
    adjust = Adjust(sample=sample, outputs=(adjusted,))
    scale = Scale(adjusted=adjusted, outputs=(result,))
    entry = ArtifactFlow(adjust, artifact=sample)
    graph = GraphDefinition(entry, ArtifactFlow(scale, artifact=adjusted),
                            entry_flows=entry)
    graph.bind_resources({adjust.calibration: calibration})
    graph.confirm()
    return graph, sample, result, calibration, scale


def main() -> None:
    graph, sample, result, calibration, scale = build_graph()
    # Fresh builders per submission; the same confirmed graph is reused.
    cases = [(3, 10, 2, 26, (10,)),
             (5, 10, 3, 45, ()),
             (5, 20, 2, 50, (20,))]
    with Engine() as engine:
        for value, offset, factor, expected, loads in cases:
            run = engine.submit(
                graph, ArtifactContext({sample: value}),
                ConfigContext({calibration.offset: offset, scale.factor: factor}),
            )
            run.wait(timeout=5)
            assert run.state is ContextState.FINISHED, run.report.data.failure
            assert run.artifact(result).value == expected
            assert run.records("result")[-1].value == expected
            # Setup records belong only to the run that actually loaded a resource.
            assert tuple(r.value for r in run.records("calibration_loaded")) == loads
            print(expected)


if __name__ == "__main__":
    main()
