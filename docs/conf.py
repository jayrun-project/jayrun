from pathlib import Path
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
html_title = f"Jayrun {release} documentation"
html_static_path = ["_static"]
