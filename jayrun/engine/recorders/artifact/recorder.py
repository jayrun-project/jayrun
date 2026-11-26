from __future__ import annotations

from collections import deque

from ...history_budget import _HistoryBudget

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
        self._history_budget: _HistoryBudget | None = None
        self._state = RecorderState.PENDING

    def initialize(
        self,
        artifacts: tuple[Artifact, ...],
        *,
        iteration: int = 1,
        history_limit: int | None = None,
    ) -> None:
        if self._state is RecorderState.RUNNING:
            raise RuntimeError("recorder is already running")
        if type(iteration) is not int or iteration < 1:
            raise ValueError("iteration must be a positive int")
        self._iteration = iteration
        self._state = RecorderState.RUNNING
        self._records: dict[Artifact, deque[ArtifactRecord] | ArtifactRecord | None] = {
            artifact: deque(maxlen=history_limit) if self._keep_history else None for artifact in artifacts
        }

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
            if isinstance(records, deque):
                artifact_records = tuple(records) or (self._unregistered_record(),)
            else:
                artifact_records = (records or self._unregistered_record(),)

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

        records = self._records[artifact]
        if isinstance(records, deque):
            if self._history_budget is not None:
                self._history_budget.account()
            records.append(record)
        else:
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
