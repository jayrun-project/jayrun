from collections.abc import Iterable
from dataclasses import dataclass

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name

from .definition.requirement import RequirementDefinition

RequirementKey = tuple[str, str | None]

if not hasattr(SpecifierSet, "is_unsatisfiable") or not hasattr(
    SpecifierSet,
    "to_range",
):
    raise RuntimeError(
        "Requirement resolution requires packaging>=26.3,<27."
    )


class RequirementConflictError(ValueError):
    pass


@dataclass(slots=True)
class _RequirementGroup:
    name: str
    extras: set[str]
    specifier: SpecifierSet
    marker: str | None
    declarations: list[str]


def merge_requirements(
    declarations: Iterable[str],
) -> tuple[RequirementDefinition, ...]:
    groups: dict[RequirementKey, _RequirementGroup] = {}

    for declaration in declarations:
        requirement = _parse_requirement(declaration)
        key = _requirement_key(requirement)
        group = groups.get(key)

        if group is None:
            if requirement.specifier.is_unsatisfiable():
                _raise_requirement_conflict(
                    key[0],
                    [declaration],
                    requirement.specifier,
                )

            groups[key] = _RequirementGroup(
                name=key[0],
                extras={canonicalize_name(extra) for extra in requirement.extras},
                specifier=requirement.specifier,
                marker=key[1],
                declarations=[declaration],
            )
            continue

        specifier = group.specifier & requirement.specifier
        combined_declarations = [*group.declarations, declaration]

        if specifier.is_unsatisfiable():
            _raise_requirement_conflict(
                group.name,
                combined_declarations,
                specifier,
            )

        group.extras.update(
            canonicalize_name(extra) for extra in requirement.extras
        )
        group.specifier = specifier
        group.declarations = combined_declarations

    return tuple(
        RequirementDefinition(
            name=group.name,
            extras=tuple(sorted(group.extras)),
            specifier=str(group.specifier.to_range().to_specifier_set()),
            marker=group.marker,
        )
        for group in groups.values()
    )


def requirement_key(declaration: str) -> RequirementKey:
    return _requirement_key(_parse_requirement(declaration))


def _parse_requirement(declaration: str) -> Requirement:
    if not isinstance(declaration, str):
        raise TypeError(
            "Requirement declarations must be strings, "
            f"got {type(declaration).__name__!r}."
        )

    try:
        requirement = Requirement(declaration)
    except InvalidRequirement as error:
        raise ValueError(f"Invalid requirement {declaration!r}.") from error

    if requirement.url is not None:
        raise ValueError(
            f"Direct URL requirement {declaration!r} is not supported."
        )

    return requirement


def _requirement_key(requirement: Requirement) -> RequirementKey:
    marker = str(requirement.marker) if requirement.marker is not None else None
    return canonicalize_name(requirement.name), marker


def _raise_requirement_conflict(
    name: str,
    declarations: list[str],
    specifier: SpecifierSet,
) -> None:
    constraints = "\n".join(
        f"  {declaration!r}" for declaration in declarations
    )
    raise RequirementConflictError(
        f"Conflicting requirements for {name!r}:\n"
        f"{constraints}\n"
        f"The combined constraint {str(specifier)!r} cannot be satisfied."
    )
