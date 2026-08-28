from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..artifact.properties import ArtifactProperty


class ValidationStatus(Enum):
    MATCH = "match"
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"


@dataclass(slots=True, frozen=True)
class PropertyValidationReport:
    property_name: str
    target_declared: bool
    source_declared: bool
    target_value: object | None
    source_value: object | None
    status: ValidationStatus
    reason: str | None = None

    def __repr__(self) -> str:
        name = self.property_name.removesuffix("Property")
        target_value = (
            repr(self.target_value) if self.target_declared else "not declared"
        )
        source_value = (
            repr(self.source_value) if self.source_declared else "not declared"
        )
        lines = [
            f"{name}: {self.status.value.upper()}",
            f"  target: {target_value}",
            f"  source: {source_value}",
        ]

        if self.reason is not None:
            lines.append(f"  Reason: {self.reason}")

        return "\n".join(lines)


@dataclass(slots=True, frozen=True)
class ArtifactValidationReport:
    status: ValidationStatus
    property_reports: tuple[PropertyValidationReport, ...]

    @property
    def valid(self) -> bool:
        return self.status is not ValidationStatus.MISMATCH

    @property
    def has_unknowns(self) -> bool:
        return any(
            report.status is ValidationStatus.UNKNOWN
            for report in self.property_reports
        )

    def __repr__(self) -> str:
        lines = [f"Validation: {self.status.value.upper()}"]

        for report in self.property_reports:
            lines.extend(f"  {line}" for line in repr(report).splitlines())

        return "\n".join(lines)


class ArtifactValidator:
    def validate(
        self,
        target_properties: tuple[ArtifactProperty, ...],
        source_properties: tuple[ArtifactProperty, ...],
    ) -> ArtifactValidationReport:
        target_by_type = {
            type(artifact_property): artifact_property
            for artifact_property in target_properties
        }
        source_by_type = {
            type(artifact_property): artifact_property
            for artifact_property in source_properties
        }
        property_types = tuple(target_by_type) + tuple(
            property_type
            for property_type in source_by_type
            if property_type not in target_by_type
        )
        property_reports = tuple(
            self._validate_property(
                property_type,
                target_by_type.get(property_type),
                source_by_type.get(property_type),
            )
            for property_type in property_types
        )
        return ArtifactValidationReport(
            status=self._resolve_status(property_reports),
            property_reports=property_reports,
        )

    @staticmethod
    def _validate_property(
        property_type: type[ArtifactProperty],
        target_property: ArtifactProperty | None,
        source_property: ArtifactProperty | None,
    ) -> PropertyValidationReport:
        property_name = property_type.__name__
        source_declared = source_property is not None
        target_value = target_property.value if target_property is not None else None
        source_value = source_property.value if source_property is not None else None

        if target_property is None:
            return PropertyValidationReport(
                property_name=property_name,
                target_declared=False,
                source_declared=source_declared,
                target_value=None,
                source_value=source_value,
                status=ValidationStatus.UNKNOWN,
                reason="The target does not declare this property.",
            )

        if source_property is None:
            return PropertyValidationReport(
                property_name=property_name,
                target_declared=True,
                source_declared=False,
                target_value=target_value,
                source_value=None,
                status=ValidationStatus.UNKNOWN,
                reason="The source does not declare this property.",
            )

        if target_property.accepts(source_property):
            return PropertyValidationReport(
                property_name=property_name,
                target_declared=True,
                source_declared=True,
                target_value=target_value,
                source_value=source_value,
                status=ValidationStatus.MATCH,
            )

        return PropertyValidationReport(
            property_name=property_name,
            target_declared=True,
            source_declared=True,
            target_value=target_value,
            source_value=source_value,
            status=ValidationStatus.MISMATCH,
            reason=(
                f"target accepts {target_value!r}, but source provides {source_value!r}."
            ),
        )

    @staticmethod
    def _resolve_status(
        property_reports: tuple[PropertyValidationReport, ...],
    ) -> ValidationStatus:
        if any(
            report.status is ValidationStatus.MISMATCH for report in property_reports
        ):
            return ValidationStatus.MISMATCH

        if not property_reports or any(
            report.status is ValidationStatus.UNKNOWN for report in property_reports
        ):
            return ValidationStatus.UNKNOWN

        return ValidationStatus.MATCH
