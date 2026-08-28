from __future__ import annotations

from ....core.artifact.base import Artifact
from ...artifact.actor import ArtifactActor
from .artifact_state import ArtifactState
from .record import ArtifactRecord
from .state import RecorderState


class ArtifactRecorder:
    def __init__(
        self,
        *,
        keep_history: bool,
    ) -> None:
        self._keep_history = keep_history
        self._state = RecorderState.PENDING

    def initialize(self, artifacts: tuple[Artifact, ...]) -> None:
        if self._state is RecorderState.RUNNING:
            raise RuntimeError("recorder is already running")
        self._iteration = 1
        self._state = RecorderState.RUNNING
        self._records: dict[Artifact, list[ArtifactRecord] | ArtifactRecord | None] = {}

        for artifact in artifacts:
            if self._keep_history:
                self._records[artifact] = []
            else:
                self._records[artifact] = None

        self._report: dict[Artifact, tuple[ArtifactRecord, ...]] | None = None

    def updated(
        self,
        artifact: Artifact,
        *,
        actor: ArtifactActor,
        step_index: int | None,
    ) -> None:
        self._record(
            artifact=artifact,
            state=ArtifactState.UPDATED,
            actor=actor,
            step_index=step_index,
        )

    def registered(
        self,
        artifact: Artifact,
        *,
        actor: ArtifactActor,
        step_index: int | None,
    ) -> None:
        self._record(
            artifact=artifact,
            state=ArtifactState.REGISTERED,
            actor=actor,
            step_index=step_index,
        )

    def cleared(
        self,
        artifact: Artifact,
        *,
        actor: ArtifactActor,
        step_index: int | None,
    ) -> None:
        self._record(
            artifact=artifact,
            state=ArtifactState.CLEARED,
            actor=actor,
            step_index=step_index,
        )

    def repeat(self) -> None:
        self._require_running()
        self._iteration += 1

    def stop(self) -> None:
        if self._state is RecorderState.STOPPED:
            return
        self._require_running()

        self._report = {}
        for artifact, records in self._records.items():
            if self._keep_history:
                artifact_records = tuple(records)
            elif records is None:
                artifact_records = ()
            else:
                artifact_records = (records,)

            if not artifact_records:
                artifact_records = (self._unregistered_record(),)

            self._report[artifact] = artifact_records

        self._records = {}
        self._state = RecorderState.STOPPED

    @property
    def report(self) -> dict[Artifact, tuple[ArtifactRecord, ...]]:
        if self._state is not RecorderState.STOPPED or self._report is None:
            raise RuntimeError("recorder has not stopped")
        return self._report

    def _record(
        self,
        artifact: Artifact,
        *,
        state: ArtifactState,
        actor: ArtifactActor,
        step_index: int | None,
    ) -> None:
        self._require_running()

        if artifact not in self._records:
            raise KeyError(f"unknown artifact: {artifact!r}")

        record = ArtifactRecord(
            state=state,
            actor=actor,
            step_index=step_index,
            iteration=self._iteration,
        )

        if self._keep_history:
            records = self._records[artifact]
            if not isinstance(records, list):
                raise TypeError("artifact history store is invalid")
            records.append(record)
            return

        self._records[artifact] = record

    def _unregistered_record(self) -> ArtifactRecord:
        return ArtifactRecord(
            state=ArtifactState.UNREGISTERED,
            actor=None,
            step_index=None,
            iteration=self._iteration,
        )

    def _require_running(self) -> None:
        if self._state is not RecorderState.RUNNING:
            raise RuntimeError("recorder is not running")
