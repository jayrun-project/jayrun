"""Shared context presentation assets; no service or execution dependencies."""
from importlib.resources import files
import json


def panels_script() -> str:
    return files(__package__).joinpath("_workspace.js").read_text(encoding="utf-8")


def theme_style() -> str:
    return files(__package__).joinpath("_theme.css").read_text(encoding="utf-8")


def workspace_style() -> str:
    return files(__package__).joinpath("_workspace.css").read_text(encoding="utf-8") + theme_style()


def standalone_script() -> str:
    assets = files(__package__)
    return assets.joinpath("_run.js").read_text(encoding="utf-8").replace(
        "__RUN_STYLE__", json.dumps(workspace_style().replace(":root[data-theme=dark]", ":host([data-theme=dark])").replace(":root", ":host"))
    ).replace("__RUN_COPY__", assets.joinpath("_copy.js").read_text(encoding="utf-8"))
