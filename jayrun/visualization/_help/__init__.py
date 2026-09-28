"""Private build-time help assets; portable and independent of framework runtime."""
from importlib.resources import files
import json


def _script() -> str:
    assets = files(__package__)
    return (assets.joinpath("controller.js").read_text(encoding="utf-8")
            .replace("__JAYRUN_HELP_CONTENT__", assets.joinpath("content.js").read_text(encoding="utf-8"))
            .replace("__JAYRUN_HELP_STYLE__", json.dumps(assets.joinpath("style.css").read_text(encoding="utf-8"))))
