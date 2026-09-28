"""Self-contained HTML export and browser opening; standard library only."""
from __future__ import annotations

import json
from html import escape
from importlib.resources import files
from pathlib import Path
import tempfile
import warnings
import webbrowser

from .contract import MAX_EXPORT_BYTES, validate_payload
from .layout import arrange
from ._workspace import panels_script, standalone_script, theme_style
from ._help import _script as _help_script


def viewer_script() -> str:
    """Return the offline static viewer script with its isolated theme tokens."""
    assets = files(__package__)
    css = assets.joinpath("viewer.css").read_text(encoding="utf-8") + theme_style()
    return (panels_script() + assets.joinpath("viewer.js").read_text(encoding="utf-8")
            .replace("__JAYRUN_STYLE__", json.dumps(css))
            .replace("__JAYRUN_HELP__", _help_script())
            .replace("__JAYRUN_COPY__", assets.joinpath("_copy.js").read_text(encoding="utf-8")))


def render_html(payload: dict, *, theme: str = "light", motion: bool = True,
                reiteration: bool = False, selection: str | None = None) -> str:
    """Render caller-supplied data without framework objects or external assets.

    Display options affect presentation only. The graph/registry snapshot is
    detached and checked on every call. Selection is a presentation entity ID.
    """
    if theme not in {"light", "dark"}:
        raise ValueError("theme must be light or dark")
    if type(motion) is not bool or type(reiteration) is not bool:
        raise TypeError("motion and reiteration must be booleans")
    if selection is not None and not isinstance(selection, str):
        raise TypeError("selection must be a presentation identity or None")
    data = validate_payload(payload)
    if data["kind"] == "graph":
        data = arrange(data)
    else:
        data["graphs"] = [arrange(graph) for graph in data["graphs"]]
    return _document(data, theme=theme, motion=motion, reiteration=reiteration, selection=selection)


def _render_legacy_html(data: dict, *, embedded: bool = False, theme: str = "light",
                        motion: bool = True, reiteration: bool = False,
                        selection: str | None = None) -> str:
    """Existing GraphPlotter export path using the same script and SVG viewer."""
    from ._legacy import normalize_legacy

    normalize_legacy(data)
    if type(embedded) is not bool:
        raise TypeError("embedded must be a boolean")
    if type(motion) is not bool or type(reiteration) is not bool:
        raise TypeError("motion and reiteration must be booleans")
    if selection is not None and not isinstance(selection, str):
        raise TypeError("selection must be a presentation identity or None")
    return _document(data, theme=theme, embedded=embedded, motion=motion,
                     reiteration=reiteration, selection=selection)


def _document(data: dict, *, theme: str = "light", motion: bool = True,
              reiteration: bool = False, selection: str | None = None,
              embedded: bool = False) -> str:
    if theme not in {"light", "dark"}:
        raise ValueError("theme must be light or dark")
    settings = {"theme": theme, "motion": motion, "reiteration": reiteration, "selection": selection}
    completed = data.get("completed")
    if completed:
        from ..reporting._completed import _format_evidence
        settings["report"] = _format_evidence(completed)
    encoded = json.dumps({"payload": data, "display": settings}, ensure_ascii=True, allow_nan=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    fragment = ('<jayrun-graph><script type="application/json">' + encoded
                + '</script></jayrun-graph><script>' + viewer_script() + '</script>')
    if completed:
        fragment = '<jayrun-run>' + fragment + '</jayrun-run><script>' + standalone_script() + '</script>'
    html = fragment if embedded else (
        f'<!doctype html><html lang="en" data-theme="{theme}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{escape(data.get("label", "Jayrun graph"))} · Jayrun viewer</title>'
        '<style>html,body{margin:0;min-height:100%;font-family:system-ui,sans-serif}'
        ':root{color-scheme:light;--page-bg:#f3f6fb;--page-ink:#172033}'
        ':root[data-theme=dark]{color-scheme:dark;--page-bg:#08121f;--page-ink:#e8eef8}'
        'body{background:var(--page-bg);color:var(--page-ink)}'
        'jayrun-graph{display:block;min-height:100vh}</style></head><body>'
        + '<script>document.addEventListener("jayrun-theme",event=>{const value=event.detail?.theme;'
        'if(["light","dark"].includes(value))document.documentElement.dataset.theme=value});</script>'
        + fragment + '</body></html>'
    )
    if len(html.encode("utf-8")) > MAX_EXPORT_BYTES:
        raise ValueError(f"HTML exceeds the explicit {MAX_EXPORT_BYTES}-byte export limit; nothing exported")
    return html


def save(payload: dict, path: str | Path, **display: object) -> Path:
    """Validate before writing and return the absolute HTML path."""
    html = render_html(payload, **display)
    output = Path(path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    return output


def show(payload: dict) -> Path:
    """Open a unique offline HTML snapshot; return its path for manual opening.

    No server, poller, or runtime is started. The temporary file remains usable
    after this call, since a browser may read it asynchronously.
    """
    html = render_html(payload)
    directory = Path(tempfile.mkdtemp(prefix="jayrun-plot-"))
    output = directory / "graph.html"
    output.write_text(html, encoding="utf-8")
    if not webbrowser.open(output.as_uri()):
        warnings.warn(f"No browser accepted the request. Open {output}", RuntimeWarning, stacklevel=2)
    return output
