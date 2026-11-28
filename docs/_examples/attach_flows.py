"""Calibrate two sensor channels and measure their difference in one native pass."""
from jayrun import (
    Artifact, ArtifactContext, ArtifactField, ArtifactFlow, BaseOperator,
    BaseResource, ConfigContext, ConfigField, Data, Engine, GraphDefinition, ResourceField,
)


class Calibration(BaseResource):
    def __init__(self):
        super().__init__()
        self.offset = ConfigField(value_type=int, required=False, default=0)

    def setup(self):
        return Data(value=self.offset.value)

    def teardown(self, data):
        pass


class Correct(BaseOperator):
    def __init__(self, *, hot, cold, outputs):
        super().__init__()
        self.hot = ArtifactField()
        self.cold = ArtifactField()
        self.calibration = ResourceField()
        self.outputs = (ArtifactField(), ArtifactField())

    def execute(self):
        offset = self.calibration.value
        return self.hot.value + offset, self.cold.value + offset


class Compare(BaseOperator):
    def __init__(self, *, hot, cold, outputs):
        super().__init__()
        self.hot = ArtifactField()
        self.cold = ArtifactField()
        self.outputs = (ArtifactField(), ArtifactField())

    def execute(self):
        return (self.hot.value + self.cold.value) / 2, self.hot.value - self.cold.value


class Measure(BaseOperator):
    def __init__(self, *, mean, span, outputs):
        super().__init__()
        self.mean = ArtifactField()
        self.span = ArtifactField()
        self.weight = ConfigField(value_type=int, required=False, default=1)
        self.outputs = (ArtifactField(),)

    def execute(self):
        return self.mean.value + self.weight.value * self.span.value


def main():
    hot, cold, mean, span = (Artifact(name=n) for n in ("hot", "cold", "mean", "span"))
    compare = Compare(hot=hot, cold=cold, outputs=(mean, span))
    hot_row, cold_row = (ArtifactFlow(compare, artifact=a) for a in (hot, cold))
    graph = GraphDefinition(hot_row, cold_row, entry_flows=(hot_row, cold_row))
    graph.confirm()
    assert graph.flow(graph.inspect.artifacts.by_id(0)) is hot_row
    assert graph.flow(mean) is None

    # The preparation flows supply BOTH core entries. Their outputs have no
    # consuming row of their own in the preparation procedure.
    raw_hot, raw_cold, calibrated_hot, calibrated_cold = (Artifact() for _ in range(4))
    correct = Correct(hot=raw_hot, cold=raw_cold, outputs=(calibrated_hot, calibrated_cold))
    raw_rows = [ArtifactFlow(correct, artifact=a) for a in (raw_hot, raw_cold)]

    measure_mean, measure_span, score = (Artifact() for _ in range(3))
    measure = Measure(mean=measure_mean, span=measure_span, outputs=(score,))
    mean_row = ArtifactFlow(measure, artifact=measure_mean)
    span_row = ArtifactFlow(measure, artifact=measure_span)

    procedure = graph.attach_many(
        (raw_rows[0], None, "end"), (raw_rows[1], None, "end"),
        (mean_row, mean, "end"), (span_row, span, "end"),
        translations={calibrated_hot: hot, calibrated_cold: cold},
        entry_artifacts=(raw_hot, raw_cold),
    )
    local_correct, = procedure.flow(raw_hot).operators
    local_measure, = procedure.flow(mean).operators
    assert local_measure is procedure.flow(span).operators[0]
    calibration = Calibration()
    procedure.bind_resources({local_correct.calibration: calibration})
    procedure.confirm()
    with Engine() as engine:
        run = engine.submit(procedure, ArtifactContext({raw_hot: 20, raw_cold: 12}),
                            ConfigContext({calibration.offset: 2, local_measure.weight: 3}))
        run.wait(timeout=5)
        assert run.artifact(score).value == 42.0  # (22 + 14) / 2 + 3 * (22 - 14)
        print(run.artifact(score).value)


if __name__ == "__main__":
    main()
