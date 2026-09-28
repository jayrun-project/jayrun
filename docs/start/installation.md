# Installation and setup

Jayrun requires Python 3.11 or later. Install the published package into your application's environment:

```bash
python -m pip install jayrun
```

For a checkout of the framework, run `python -m pip install -e .` from its repository root. Use a checkout containing the APIs described by this manual when the public package has not yet incorporated a change. [The public repository](https://github.com/jayrun-project/jayrun) is the source location.

Optional YAML configuration support is available with `python -m pip install "jayrun[yaml]"`. The current HTML graph viewer is bundled; plotting does not require PyVis. Tutorial dependencies, including PyTorch and web-service packages, belong to those examples and are not necessary for the small CPU examples in these guides.

## Scripts and notebooks

A script can use `with Engine() as engine:` to start an owned loop and close the engine on exit. In an async application, use async waiting and shutdown. In a notebook, use top-level `await`; do not call `asyncio.run()` inside its already-running loop. See [async applications and notebooks](../guides/runs/async.md).

The [tutorial setup guide](../tutorials/index.md) links the source, dependency files and notebooks in the repository. GPU examples require an appropriate backend and available hardware; CPU fixtures do not establish GPU behavior.

## Build this manual

From the repository root:

```bash
python -m pip install -r docs/requirements.txt
python -m sphinx -E -a -n -W --keep-going -b html docs docs/_build/html
```

The command rebuilds all pages so navigation stays consistent after changes to titles or chapter order. The documentation requirements are separate from framework runtime dependencies. Builds include local tutorial source; GitHub links are for readers and are not fetched to assemble the manual.
