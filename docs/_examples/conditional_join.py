"""Explicit tagged values keep both join inputs present; prints 10 twice."""
from jayrun import Artifact, ArtifactField, ArtifactFlow, BaseOperator, ConfigField, Data, Engine, GraphDefinition
from jayrun.context import ContextState


class TaggedChoice(BaseOperator):
    def __init__(self, *, choose_left, outputs):
        super().__init__()
        self.choose_left = ConfigField(value_type=bool, required=False, default=choose_left)
        self.outputs = (ArtifactField(), ArtifactField())

    def execute(self):
        chosen = Data(value=(True, 10))
        absent = Data(value=(False, None))
        return (chosen, absent) if self.choose_left.value else (absent, chosen)


class Select(BaseOperator):
    def __init__(self, *, left, right, outputs):
        super().__init__()
        self.left, self.right = ArtifactField(), ArtifactField()
        self.outputs = (ArtifactField(),)

    def execute(self):
        left_present, left_value = self.left.value
        right_present, right_value = self.right.value
        assert left_present != right_present
        return left_value if left_present else right_value


def main():
    for choose_left in (True, False):
        left, right, result = (Artifact() for _ in range(3))
        choice = TaggedChoice(choose_left=choose_left, outputs=(left, right))
        select = Select(left=left, right=right, outputs=(result,))
        graph = GraphDefinition(ArtifactFlow(choice, select, artifact=left),
                                ArtifactFlow(choice, select, artifact=right))
        graph.confirm()
        with Engine() as engine:
            run = engine.submit(graph)
            run.wait(timeout=5)
            assert run.state is ContextState.FINISHED, run.report.data.failure
            assert run.artifact(result).value == 10
            assert not any(e.skip_reason == 'missing_input' for e in run.report.data.executions)
            print(10)


if __name__ == '__main__':
    main()
