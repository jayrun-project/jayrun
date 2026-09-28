"""Read execution diagnostics and committed events from a small CPU run."""
from jayrun import Artifact, ArtifactField, ArtifactFlow, BaseOperator, Engine, GraphDefinition
from jayrun.context import ContextState


class Sum(BaseOperator):
    def __init__(self, *, outputs):
        super().__init__()
        self.outputs = (ArtifactField(),)

    def execute(self):
        self.execution.log("adding values")
        self.execution.start_timer("sum")
        try:
            result = sum((1, 2, 3))
        finally:
            self.execution.stop_timer("sum")
        self.execution.metric("total", float(result))
        self.context.record("total", result)
        return result


def main():
    result = Artifact(name="sum")
    graph = GraphDefinition(ArtifactFlow(Sum(outputs=(result,))))
    graph.confirm()
    with Engine() as engine:
        observer = engine.observer(capacity=256)
        try:
            run = engine.submit(graph)
            run.wait(timeout=5)
            assert run.state is ContextState.FINISHED, run.report.data.failure
        finally:
            observer.close()
        events = tuple(observer)  # Close wakes iteration; already queued events drain.
        assert events and all(e.context_id == run.context_id for e in events)
        report = run.report.data
        assert run.records("total")[-1].value == 6
        records = [record for step in report.executions for attempt in step.attempts
                   for record in attempt.records]
        assert any(getattr(record, "name", None) == "total" for record in records)
        for step in report.executions:
            print(step.step_name, step.outcome.value, step.skip_reason)
            for attempt in step.attempts:
                for record in attempt.records:
                    print(type(record).__name__)


if __name__ == "__main__":
    main()
