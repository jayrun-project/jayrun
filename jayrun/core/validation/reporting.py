from __future__ import annotations

from pathlib import Path

from .graph import GraphValidationReport


class ValidationReporter:
    """Render a graph validation result as readable text."""

    _DEFAULT_FILENAME = "graph_validation.txt"

    def __init__(self, report: GraphValidationReport) -> None:
        self._report = report

    def __str__(self) -> str:
        return self.format()

    def format(self) -> str:
        """Return the complete validation report as text."""
        status = "VALID" if self._report.valid else "INVALID"
        lines = [
            f"Graph validation: {status}",
            f"Mismatches: {len(self._report.mismatched_edges)}",
            f"Unknowns: {len(self._report.unknown_edges)}",
            "",
            "NODES",
            "-----",
        ]

        for node in self._report.nodes:
            lines.append(repr(node))
            lines.append("")

        lines.extend(("EDGES", "-----"))

        for edge in self._report.edges:
            lines.append(repr(edge))
            lines.append("")

        return "\n".join(lines).rstrip()

    def print(self) -> None:
        """Print the complete validation report to standard output."""
        print(self.format())

    def save(self, path: str | Path | None = None) -> Path:
        """Write the report to UTF-8 text and return its absolute path."""
        output_path = Path(
            path if path is not None else self._DEFAULT_FILENAME
        ).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            self.format() + "\n",
            encoding="utf-8",
        )
        return output_path
