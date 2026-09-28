# Releasing Jayrun

Public content lives in `jayrun/`, `docs/` and `tutorials/`; `.github/` contains
release infrastructure. `docs/_build/` is generated locally and must be excluded
from the public source/export and package artifacts; keep `docs/_static/` assets.
Read the Docs generates its own build output. Internal audits, tests and evidence stay in the private
development repository and must never enter the public Git history.

1. Update the package version in `pyproject.toml` and `jayrun/__init__.py` together.
   Add the release changelog and preserve older entries. Component identity versions
   on operator/resource/serializer classes are independent of the package version.
2. From the development repository, export to an empty directory:
   `python .github/scripts/release_check.py --export /path/to/public-candidate`.
   Review the public tree against the latest public main in a separate checkout.
   Do not push the private development branch/history. Preserve existing public history.
3. In that public tree, run `python .github/scripts/release_check.py`, `python -m build`,
   `python -m twine check --strict dist/*` and
   `python .github/scripts/release_check.py --dist dist`. Install the wheel into a
   clean environment and run `python -I .github/scripts/wheel_smoke.py --source /path/to/public-candidate`.
   CI checks Python 3.11–3.14 with minimum/current packaging and optional YAML.
4. Install `docs/requirements.txt`, build with
   `python -m sphinx -a -E -W --keep-going -b html docs docs/_build/html`, then run
   `python .github/scripts/check_links.py --html docs/_build/html`.
5. Verify the PyPI Trusted Publisher for owner `jayrun-project`, repository `jayrun`,
   workflow `publish.yml` and environment `pypi`. Check the GitHub environment rules
   and Read the Docs repository/webhook configuration. Local checks do not verify
   these account settings. A TestPyPI prerelease is optional and requires separate setup.
6. After publication approval, push reviewed public changes, wait for main CI and
   Read the Docs, and use the Documentation workflow's manual `check_live` option
   to check deployed links. Check candidate links locally before deployment; new
   public paths can legitimately return 404 until publication finishes.
7. Only after the exact release commit passes its gates, create/push its reviewed
   `vX.Y.Z` tag. **Pushing this tag publishes to PyPI automatically.** The publish
   workflow checks the exact built wheel on all four supported Python versions
   before uploading it, then creates a GitHub Release with the distributions.
8. Verify installation from PyPI and the hosted documentation. Activate the tag/stable
   documentation on Read the Docs if desired; README links intentionally use latest.

Save all future dashboard screenshots/captures under `docs/_static/`.
`docs/_static/dashboard_preview.html` is the canonical offline capture; README PNGs
belong in `docs/_static/screenshots/`. Never recreate `_screenshot/`. The generator
preserves the capture, regenerates the other viewers and updates the visualization
manifest. Captured IDs, timings and version labels describe the recorded session.
