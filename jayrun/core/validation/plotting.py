from __future__ import annotations

import colorsys
import webbrowser
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

from ..artifact.base import Artifact
from .graph import GraphEdge, GraphValidationReport, OperatorNode

if TYPE_CHECKING:
    from pyvis.network import Network


class GraphPlotter:
    """Build, display, or save an interactive graph-validation visualization."""

    _X_SPACING = 250
    _Y_SPACING = 120
    _OPERATOR_COLOR = "#475569"
    _OPERATOR_BORDER = "#334155"
    _OPERATOR_WIDTH = 116
    _OPERATOR_HEIGHT = 50
    _ARTIFACT_SATURATION = 0.62
    _ARTIFACT_LIGHTNESS = 0.50
    _GOLDEN_RATIO = 0.618033988749895

    def __init__(
        self,
        report: GraphValidationReport,
        artifacts: tuple[Artifact, ...],
    ) -> None:
        self._report = report
        self._artifacts = artifacts

    def build(self) -> Network:
        """Build and return the underlying PyVis network."""
        return self._build_network(notebook=False)

    def show(
        self,
        name: str = "graph_validation.html",
        notebook: bool = False,
    ) -> object | None:
        """Write and display an interactive HTML graph.

        Args:
            name: Output HTML path.
            notebook: Return an IPython ``IFrame`` instead of opening a browser.
        """
        output_path = self._write_html(name, notebook=notebook)

        if notebook:
            try:
                from IPython.display import IFrame
            except ImportError as error:
                raise RuntimeError("IPython is required when notebook=True.") from error

            return IFrame(
                str(output_path),
                width="100%",
                height="850px",
            )

        webbrowser.open(output_path.as_uri())
        return None

    def save(self, path: str | Path | None = None) -> Path:
        """Write an interactive HTML graph and return its absolute path."""
        return self._write_html(
            path or "graph_validation.html",
            notebook=False,
        )

    def _write_html(
        self,
        path: str | Path,
        *,
        notebook: bool,
    ) -> Path:
        output_path = Path(path).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        network = self._build_network(notebook=notebook)
        html = network.generate_html(
            name=output_path.name,
            notebook=notebook,
        )
        html = html.replace(
            "</head>",
            "<style>.vis-tooltip { white-space: pre-line !important; }</style></head>",
            1,
        )
        output_path.write_text(html, encoding="utf-8")
        return output_path

    def _build_network(self, *, notebook: bool) -> Network:
        Network = self._network_class()
        network = Network(
            height="850px",
            width="100%",
            directed=True,
            bgcolor="#FFFFFF",
            font_color="#111827",
            notebook=notebook,
            cdn_resources="remote" if notebook else "local",
        )
        network.toggle_physics(False)

        for node in self._report.nodes:
            options = {
                "label": node.label,
                "title": self._tooltip(node),
                "x": node.x_position * self._X_SPACING,
                "y": node.y_position * self._Y_SPACING,
                "fixed": False,
                "physics": False,
            }

            if isinstance(node, OperatorNode):
                options.update(
                    shape="image",
                    image=self._operator_image,
                    size=30,
                    shapeProperties={"useImageSize": True},
                    font={"color": "#111827", "size": 18},
                )
            else:
                options.update(
                    shape="dot",
                    size=20,
                    color=self._artifact_colors[node.artifact],
                    font={"color": "#111827", "size": 14},
                )

            network.add_node(node.node_id, **options)

        for edge in self._report.edges:
            network.add_edge(
                edge.source,
                edge.target,
                label=edge.label,
                title=self._tooltip(edge),
                color=self._edge_color(edge),
                width=6 if edge.mismatched else 5,
                dashes=False,
                arrows="to",
                font={
                    "color": self._edge_font_color(edge),
                    "size": 14,
                    "align": "middle",
                },
                smooth={
                    "type": "cubicBezier",
                    "forceDirection": "horizontal",
                    "roundness": 0.35,
                },
            )

        return network

    @staticmethod
    def _edge_font_color(edge: GraphEdge) -> str:
        if edge.mismatched:
            return "#AD1F1F"

        if edge.unknown:
            return "#92400E"

        return "#111827"

    def _edge_color(self, edge: GraphEdge) -> str:
        return self._artifact_colors[edge.artifact]

    @cached_property
    def _artifact_colors(self) -> dict[Artifact, str]:
        return {
            artifact: self._artifact_color(index)
            for index, artifact in enumerate(self._artifacts)
        }

    @cached_property
    def _operator_image(self) -> str:
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{self._OPERATOR_WIDTH}" height="{self._OPERATOR_HEIGHT}" '
            f'viewBox="0 0 {self._OPERATOR_WIDTH} {self._OPERATOR_HEIGHT}">'
            f'<rect x="1" y="1" width="{self._OPERATOR_WIDTH - 2}" '
            f'height="{self._OPERATOR_HEIGHT - 2}" rx="5" '
            f'fill="{self._OPERATOR_COLOR}" stroke="{self._OPERATOR_BORDER}" '
            f'stroke-width="2"/>'
            "</svg>"
        )
        return f"data:image/svg+xml;charset=utf-8,{quote(svg)}"

    @classmethod
    def _artifact_color(cls, index: int) -> str:
        hue = (0.57 + index * cls._GOLDEN_RATIO) % 1.0
        red, green, blue = colorsys.hls_to_rgb(
            hue,
            cls._ARTIFACT_LIGHTNESS,
            cls._ARTIFACT_SATURATION,
        )
        return "#{:02X}{:02X}{:02X}".format(
            round(red * 255),
            round(green * 255),
            round(blue * 255),
        )

    @staticmethod
    def _tooltip(value: object) -> str:
        return repr(value).replace("\r\n", "\n").replace("\r", "\n")

    @staticmethod
    def _network_class() -> type[Network]:
        try:
            from pyvis.network import Network
        except ImportError as error:
            raise RuntimeError("PyVis is required for GraphValidator.plot.") from error

        return Network
