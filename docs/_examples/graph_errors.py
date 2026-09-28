"""Intentional invalid graphs: execute this file to verify the diagnostics."""
from jayrun import Artifact, ArtifactField, ArtifactFlow, BaseOperator, GraphDefinition


class Consumer(BaseOperator):
    def __init__(self, *, left, right=None):
        super().__init__()
        self.left = ArtifactField()
        self.right = ArtifactField(required=False)
        self.outputs = ()

    def execute(self):
        return ()


class Producer(BaseOperator):
    def __init__(self, *, outputs):
        super().__init__()
        self.outputs = (ArtifactField(),)

    def execute(self):
        return 1


def invalid_fan_out():
    left, right = Artifact(), Artifact()
    first = Consumer(left=left, right=None)
    second = Consumer(left=left, right=right)
    flows = ArtifactFlow(first, artifact=left), ArtifactFlow(second, artifact=right)
    # Both branches want left, but the first consumed it without regeneration.
    GraphDefinition(*flows, entry_flows=flows)


def invalid_fan_in():
    result = Artifact()
    # Two independent roots compete to produce the same active artifact.
    GraphDefinition(ArtifactFlow(Producer(outputs=(result,))),
                    ArtifactFlow(Producer(outputs=(result,))))


def main():
    for scenario, fragment in ((invalid_fan_out, 'unavailable artifacts'),
                               (invalid_fan_in, 'Fan-in')):
        try:
            scenario()
        except ValueError as error:
            assert fragment in str(error), str(error)
            print(f'{scenario.__name__}: ValueError ({fragment})')
        else:
            raise AssertionError('An invalid declaration was accepted')


if __name__ == '__main__':
    main()
