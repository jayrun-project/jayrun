from pathlib import Path
import importlib
import inspect
import os
import re
import sys
import tomllib


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

metadata = tomllib.loads(
    (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
)["project"]

project = "Jayrun"
author = "Masoud Yavari"
copyright = "2026, Masoud Yavari"
version = metadata["version"]
release = version
language = "en"

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.intersphinx",
    "sphinx.ext.napoleon",
    "sphinx.ext.linkcode",
]

source_suffix = {
    ".md": "markdown",
    ".rst": "restructuredtext",
}
master_doc = "index"
exclude_patterns = ["_build"]
nitpicky = True
# Public autodoc signatures may contain implementation-only type hints. They
# remain useful as plain type names, but the internal modules are deliberately
# absent from the public object inventory.
nitpick_ignore_regex = [
    ("py:class", r"jayrun\.core\..*"),
    ("py:class", r"jayrun\.engine\..*"),
    ("py:class", r"asyncio\.events\.AbstractEventLoop"),
    ("py:class", r"jayrun\.persistence\.backend\.(StoreStatistics|BackendOptions|WriteBatch|WriteReceipt|ProfileQuery|ProfileAggregate)"),
    ("py:class", r"jayrun\.persistence\.records\.Header"),
    ("py:class", r"_RunReporter"),  # Private implementation of run.report.
]
primary_domain = "py"
toc_object_entries = False

autosummary_generate = True
autodoc_typehints = "signature"
autodoc_member_order = "bysource"
napoleon_google_docstring = True
napoleon_numpy_docstring = False

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}

myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "fieldlist",
]
myst_heading_anchors = 4

html_theme = "furo"
html_title = "Jayrun documentation"
html_static_path = ["_static"]
templates_path = ["_templates"]
html_css_files = ["manual.css"]
html_theme_options = {
    "source_repository": "https://github.com/jayrun-project/jayrun/",
    "source_branch": "main",
    "source_directory": "docs/",
}


def linkcode_resolve(domain, info):
    """Link public facade objects to their actual public-repository source file."""
    if domain != "py" or not info.get("module"):
        return None
    try:
        obj = importlib.import_module(info["module"])
        for name in info["fullname"].split("."):
            obj = getattr(obj, name)
        if isinstance(obj, property):
            obj = obj.fget
        source = inspect.getsourcefile(inspect.unwrap(obj))
        if source is None:
            return None
        relative = Path(source).resolve().relative_to(PROJECT_ROOT)
    except (AttributeError, ImportError, TypeError, ValueError):
        return None
    # Main can differ from the local checkout; file links avoid misleading line offsets.
    ref = os.environ.get("JAYRUN_SOURCE_REF", "main")
    return f"https://github.com/jayrun-project/jayrun/blob/{ref}/{relative.as_posix()}"


_REFERENCE_DESCRIPTIONS = {
    "jayrun.registry.GraphIdentity": "A graph registry identity: a tuple of the application key and graph version, for example ('transform', '1').",
    "jayrun.context.ContextEvent": "Union of committed state/Stop/value/transfer events and forwarded control-request events. Consume these through an Engine observer or self.runtime.events.",
    "jayrun.context.ContextHistoryEntry": "Union of state transitions, Stop acceptance, iteration starts, control requests and engine-ownership changes retained in context history.",
    "jayrun.placement.PlacementLocation": "A single-device Placement or a PlacementGroup. Data carries one of these values alongside its payload.",
    "jayrun.persistence.Database.open": "Open this component for standalone inspection and return it. read_only=True is the default. Engine-owned databases are opened by the Engine; do not open them separately.",
    "jayrun.persistence.Database.close": "Close a standalone component's storage lane after admitted work settles. Engine-owned databases are closed by their Engine.",
    "jayrun.persistence.Database.status": "Current immutable storage status, including pending work, failed publications and capture gaps.",
}
_QUERY_DESCRIPTIONS = {
    "query_sessions": "Return a bounded page of session headers matching SessionQuery. Continue with the returned next_cursor in the next query.",
    "query_contexts": "Return a bounded page of context headers matching HistoryQuery. Continue with the returned next_cursor in the next query. Reader calls additionally apply the granted session scope.",
    "get_session": "Return the stored session detail for session_id, or None when unavailable or outside the reader's scope.",
    "get_context": "Return the stored context account and available layout for the given session_id/context_id pair, or None when unavailable or outside the reader's scope. Inspect coverage before assuming full detail.",
}


def current_public_docstrings(app, what, name, obj, options, lines):
    """Add reader-facing descriptions to otherwise bare public reference entries."""
    if name in _REFERENCE_DESCRIPTIONS:
        lines[:] = [_REFERENCE_DESCRIPTIONS[name]]
    if name.startswith(("jayrun.persistence.Database.", "jayrun.persistence.DatabaseReader.")):
        member = name.rsplit(".", 1)[-1]
        plain = member.removesuffix("_async")
        if plain in _QUERY_DESCRIPTIONS:
            lines[:] = [_QUERY_DESCRIPTIONS[plain]]
        if member.endswith("_async") and not lines:
            lines[:] = [f"Non-blocking counterpart of {plain} with the same scope and completion rules."]
    if name == "jayrun.Engine.pressure":
        lines[:] = [line.replace(":attr:`contexts`", ":attr:`unfinished_contexts`") for line in lines]
    if name == "jayrun.persistence.Backend":
        lines[:] = [line.replace("P2 domain conformance contract", "persistence backend contract") for line in lines]
    if name == "jayrun.inspection.GraphPlotter.build":
        lines[:] = [line.replace("This replaces the former PyVis Network return type.", "Use this payload with the bundled viewer.") for line in lines]


def readable_signatures(app, what, name, obj, options, signature, return_annotation):
    if signature is None:
        return None
    if name == "jayrun.settings.EngineSettings":
        # The current Sphinx renderer drops part of this nested union. The
        # parameter description states its single-device/tuple type explicitly.
        signature = re.sub(r"runtime_devices:.*?(?=\s*=\s*\(\))", "runtime_devices", signature)
    if name == "jayrun.persistence.Database":
        # These are default-constructed policy objects, documented in full below.
        signature = re.sub(r"(RetentionPolicy|DatabaseLimits|ValueLimits)\([^()]*\)", r"\1()", signature)
    return signature, return_annotation


def setup(app):
    app.connect("autodoc-process-docstring", current_public_docstrings)
    app.connect("autodoc-process-signature", readable_signatures)
