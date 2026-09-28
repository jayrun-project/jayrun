"""Declaration consistency using stable public packaging primitives.

This is a satisfiability check, not an index/installer. The finite cells below
partition the *unbounded* PEP 440 version domain at every declaration boundary;
there is no fixed major-version, suffix-number, or release-depth search limit.
See the private Stage 1 audit for the partition argument and test evidence.
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator
from packaging import __version__ as _packaging_version
from packaging.specifiers import Specifier, SpecifierSet
from packaging.version import InvalidVersion, Version


if Version(_packaging_version) < Version("25"):
    raise RuntimeError("Requirement resolution requires packaging>=25.")


def _numbers(boundaries: Iterable[int]) -> tuple[int, ...]:
    """One representative of each integer boundary and nonempty open cell."""
    values = {0}
    for value in boundaries:
        values.add(value)
        values.add(value + 1)
    return tuple(sorted(values))


def _base(epoch: int, release: tuple[int, ...]) -> str:
    return (f"{epoch}!" if epoch else "") + ".".join(map(str, release))


def _release_cells(versions: tuple[Version, ...]) -> Iterator[Version]:
    # Version comparison pads release tuples with zeros. Appending more zeros
    # than any declared release followed by 1 supplies a witness strictly above
    # a boundary and below the next distinct boundary, even for 1 vs 1.0.0.1.
    boundaries = {Version("0")}
    boundaries.update(Version(v.base_version) for v in versions)
    depth = max((len(v.release) for v in versions), default=1) + 1
    for value in sorted(boundaries):
        yield value
        release = value.release + (0,) * (depth - len(value.release)) + (1,)
        yield Version(_base(value.epoch, release))


def _suffix_cells(base: Version, versions: tuple[Version, ...]) -> Iterator[Version]:
    relevant = tuple(v for v in versions if Version(v.base_version) == base)
    text = base.base_version
    # The suffix is lexicographic: pre kind/number, post number, dev number.
    # Absent fields and the dev-only region are independent cells. Subdivide
    # only at boundaries sharing the already selected prefix, not a Cartesian
    # product of every number in unrelated version clauses.
    pres: list[tuple[str, int] | None] = [None]
    for label in ("a", "b", "rc"):
        pres.extend((label, n) for n in _numbers(v.pre[1] for v in relevant if v.pre and v.pre[0] == label))
    for pre in pres:
        pre_text = text + (f"{pre[0]}{pre[1]}" if pre else "")
        matching_pre = tuple(v for v in relevant if v.pre == pre)
        posts = (None, *_numbers(v.post for v in matching_pre if v.post is not None))
        for post in posts:
            post_text = pre_text + (f".post{post}" if post is not None else "")
            matching_post = tuple(v for v in matching_pre if v.post == post)
            yield Version(post_text)
            for dev in _numbers(v.dev for v in matching_post if v.dev is not None):
                yield Version(f"{post_text}.dev{dev}")


def _accepts(specifiers: tuple[Specifier, ...], candidate: Version) -> bool:
    return all(spec.contains(candidate, prereleases=True) for spec in specifiers)


def is_unsatisfiable(specifiers: SpecifierSet) -> bool:
    """Whether the declarations admit no version, including prerelease fallback.

    Membership (including exclusive pre/post rules) is owned by the installed
    packaging version. Local versions need no separate infinite search: absent
    a local equality/literal pin, removing the local label preserves a witness.
    """
    if not isinstance(specifiers, SpecifierSet):
        raise TypeError("specifiers must be a SpecifierSet")
    clauses = tuple(sorted(specifiers, key=str))
    literals = {s.version.lower() for s in clauses if s.operator == "==="}
    if literals:
        if len(literals) != 1:
            return True
        literal = next(iter(literals))
        others = tuple(s for s in clauses if s.operator != "===")
        try:
            candidate = Version(literal)
        except InvalidVersion:
            return bool(others)  # Only literal equality admits a non-PEP-440 value.
        return not _accepts(others, candidate)
    pins = [Version(s.version) for s in clauses if s.operator == "==" and not s.version.endswith(".*")]
    if pins:
        candidate = next((v for v in pins if v.local is not None), pins[0])
        return not _accepts(clauses, candidate)
    versions = []
    for spec in clauses:
        wildcard = spec.version.endswith(".*")
        version = Version(spec.version[:-2] if wildcard else spec.version)
        versions.append(version)
        if wildcard or spec.operator == "~=":
            prefix = version.release if wildcard else version.release[:-1]
            upper = (*prefix[:-1], prefix[-1] + 1)
            versions.append(Version(_base(version.epoch, upper)))
    boundaries = tuple(versions)
    for base in _release_cells(boundaries):
        for candidate in _suffix_cells(base, boundaries):
            if _accepts(clauses, candidate):
                return False
    return True


def normalize_specifiers(specifiers: SpecifierSet) -> str:
    """Stable sorted conjunction; preserve clauses instead of lossy range output.

    No new packaging range objects enter framework declarations or serialization.
    Redundant clauses may remain; accepted versions do not change.
    """
    return str(specifiers)
