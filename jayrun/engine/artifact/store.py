from __future__ import annotations

from ...core.artifact.base import Artifact
from ...core.artifact.context import ArtifactContext
from ...core.context.runtime_data import Data
from ..recorders.artifact.recorder import ArtifactRecorder
from ..settings.combined_context import CombinedContextSettings
from .actor import ArtifactActor
from .result import ArtifactResult
from .state import ArtifactStoreState


class ExecutionArtifactStore:
    def __init__(
        self,
        artifacts: tuple[Artifact, ...],
        entry_artifacts: tuple[Artifact, ...],
        feedback_artifacts: tuple[Artifact, ...],
        artifact_context: ArtifactContext,
        settings: CombinedContextSettings,
        recorder: ArtifactRecorder,
    ) -> None:
        self._artifacts = artifacts
        self._entry_artifacts = entry_artifacts
        self._feedback_artifacts = feedback_artifacts
        self._artifact_context = artifact_context
        self._settings = settings
        self._recorder = recorder
        self._iteration = 1
        self._state = ArtifactStoreState.PENDING
        self._artifact_data: dict[Artifact, Data[object]] = {}
        self._entry_data: dict[Artifact, Data[object]] = {}
        self._artifact_results: dict[Artifact, ArtifactResult] | None = None
        self._initialize()

    @property
    def state(self) -> ArtifactStoreState:
        return self._state

    @property
    def result(self) -> dict[Artifact, ArtifactResult]:
        if (
            self._state is not ArtifactStoreState.FINALIZED
            or self._artifact_results is None
        ):
            raise RuntimeError("artifact store has not been finalized")
        return self._artifact_results

    def get(self, artifact: Artifact) -> Data[object]:
        self._require_running()
        self._validate_artifact(artifact)
        return self._artifact_data[artifact]

    def update(
        self,
        artifact: Artifact,
        data: Data[object] | object | None,
        *,
        step_index: int | None = None,
        actor: ArtifactActor | None = None,
    ) -> None:
        self._require_running()
        self._validate_artifact(artifact)

        data = self._normalize_data(data)
        actor = self._resolve_actor(actor=actor, step_index=step_index)
        current = self._artifact_data[artifact]

        if current.value is None and data.value is None:
            return

        if current.value is None:
            self._recorder.registered(
                artifact=artifact,
                step_index=step_index,
                actor=actor,
            )
        elif data.value is None:
            self._recorder.cleared(
                artifact=artifact,
                step_index=step_index,
                actor=actor,
            )
        else:
            self._recorder.updated(
                artifact=artifact,
                step_index=step_index,
                actor=actor,
            )

        self._artifact_data[artifact] = data

        if actor is ArtifactActor.OPERATOR and artifact in self._feedback_artifacts:
            self._entry_data[artifact] = data

    def release_consumed(
        self,
        consumed_artifacts: tuple[Artifact, ...],
        produced_artifacts: tuple[Artifact, ...],
    ) -> None:
        self._require_running()
        produced = set(produced_artifacts)
        for artifact in consumed_artifacts:
            if artifact in produced:
                continue
            self._clear(artifact)
            if not self._can_iterate_again:
                self._entry_data.pop(artifact, None)

    def repeat(self) -> None:
        self._require_running()
        self._cleanup(set())
        self._iteration += 1
        self._recorder.repeat()
        self._restore_entry_artifacts()

    def finalize(self, *, retain_results: bool) -> None:
        if self._state is ArtifactStoreState.FINALIZED:
            return

        self._require_running()

        if not isinstance(retain_results, bool):
            raise TypeError("retain_results must be a bool")

        retained = (
            set(self._settings.artifact_policy.retained_artifacts)
            if retain_results
            else set()
        )
        self._cleanup(retained)

        self._recorder.stop()
        report = self._recorder.report
        self._artifact_results = {
            artifact: ArtifactResult(
                data=self._artifact_data[artifact],
                report=report[artifact],
            )
            for artifact in self._artifacts
        }
        self._artifact_data.clear()
        self._entry_data.clear()
        self._state = ArtifactStoreState.FINALIZED

    def _initialize(self) -> None:
        self._state = ArtifactStoreState.RUNNING
        self._recorder.initialize(artifacts=self._artifacts)
        self._artifact_data = {
            artifact: Data(value=None) for artifact in self._artifacts
        }
        self._load_entry_artifacts()

    def _load_entry_artifacts(self) -> None:
        entry_data = {
            artifact: self._artifact_context.get(artifact)
            for artifact in self._entry_artifacts
        }
        for artifact, data in entry_data.items():
            self.update(
                artifact=artifact,
                data=data,
                actor=ArtifactActor.ENTRY,
            )
            self._entry_data[artifact] = self._artifact_data[artifact]

        if self._settings.artifact_policy.release_entry_artifacts:
            self._artifact_context.clear_entries()

    def _restore_entry_artifacts(self) -> None:
        for artifact, data in self._entry_data.items():
            self.update(
                artifact=artifact,
                data=data,
                actor=ArtifactActor.ENTRY,
            )

    @property
    def _can_iterate_again(self) -> bool:
        if self._settings.max_iterations is None:
            return True
        return self._iteration < self._settings.max_iterations

    def _cleanup(self, retained_artifacts: set[Artifact]) -> None:
        for artifact, artifact_data in tuple(self._artifact_data.items()):
            if artifact_data.value is None:
                continue
            if artifact in retained_artifacts:
                continue
            self.update(
                artifact=artifact,
                data=None,
                actor=ArtifactActor.INTERNAL,
            )

    def _clear(self, artifact: Artifact) -> None:
        self.update(
            artifact=artifact,
            data=None,
            actor=ArtifactActor.INTERNAL,
        )

    def _normalize_data(self, data: Data[object] | object | None) -> Data[object]:
        if isinstance(data, Data):
            return data
        return Data(value=data)

    def _resolve_actor(
        self,
        *,
        actor: ArtifactActor | None,
        step_index: int | None,
    ) -> ArtifactActor:
        if step_index is not None:
            if actor not in (None, ArtifactActor.OPERATOR):
                raise ValueError("step_index can only be used with an operator actor")
            return ArtifactActor.OPERATOR
        if actor is None:
            raise ValueError("actor is required when step_index is not provided")
        if not isinstance(actor, ArtifactActor):
            raise TypeError("actor must be an ArtifactActor")
        return actor

    def _validate_artifact(self, artifact: Artifact) -> None:
        if artifact not in self._artifact_data:
            raise KeyError(f"unknown artifact: {artifact!r}")

    def _require_running(self) -> None:
        if self._state is not ArtifactStoreState.RUNNING:
            raise RuntimeError("artifact store is not running")
