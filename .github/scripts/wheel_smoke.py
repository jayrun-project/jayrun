"""Run with python -I after installing a wheel; never import checkout code."""
from __future__ import annotations

import argparse
import importlib
import importlib.metadata
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--yaml', action='store_true')
    args = parser.parse_args()
    root = args.source.resolve()
    import jayrun
    project = tomllib.loads((root / 'pyproject.toml').read_text())['project']
    assert sys.flags.isolated, 'Use python -I'
    assert not Path(jayrun.__file__).resolve().is_relative_to(root), jayrun.__file__
    assert importlib.metadata.version('jayrun') == jayrun.__version__ == project['version']
    namespaces = ('context', 'settings', 'inspection', 'registry', 'validation', 'properties',
                  'placement', 'persistence', 'serialization', 'visualization', 'dashboard')
    for module in [jayrun, *(importlib.import_module('jayrun.' + name) for name in namespaces)]:
        for name in getattr(module, '__all__', ()):
            getattr(module, name)
    for code in re.findall(r'```python\n(.*?)```', (root / 'README.md').read_text(), re.S):
        exec(compile(code, 'README.md', 'exec'), {})
    with tempfile.TemporaryDirectory(prefix='jayrun-wheel-') as temporary:
        examples = Path(temporary) / 'examples'
        shutil.copytree(root / 'docs/_examples', examples, ignore=shutil.ignore_patterns('__pycache__'))
        for path in sorted(examples.glob('*.py')):
            subprocess.run([sys.executable, '-I', '-B', '-c',
                            'import sys,runpy;sys.path.insert(0,sys.argv[1]);runpy.run_path(sys.argv[2],run_name="__main__")',
                            str(examples), str(path)], cwd=temporary, check=True, timeout=30)
        sys.path.insert(0, str(examples))
        from first_graph import build_graph
        from jayrun import ArtifactContext, ConfigContext, Controller, Engine, GraphRegistry
        from jayrun.context import ContextState
        from jayrun.persistence import Database
        from jayrun.dashboard import prepare_dashboard
        graph, source, result, scale = build_graph()
        registry = GraphRegistry()
        registry.register('smoke', graph)
        for plot in (graph.plot, registry.plot):
            assert '<jayrun-graph' in plot.to_html()
        configs = ConfigContext({scale.factor: 3})
        if args.yaml:
            restored = ConfigContext()
            restored.load_yaml(configs.to_yaml(graph), graph)
            configs = restored
        with Engine(database=Database(Path(temporary) / 'history.sqlite')) as engine:
            run = engine.submit(graph, ArtifactContext({source: 7}), configs)
            run.wait(timeout=10)
            assert run.state is ContextState.FINISHED and run.artifact(result).value == 21
            assert '<jayrun-graph' in run.plot.to_html()
            engine.database.flush(timeout=10)
        with Engine() as engine:
            prepared = prepare_dashboard(port=0, duration=0.05)
            run = engine.submit(prepared.graph, artifacts=prepared.artifacts,
                                configs=prepared.configs, settings=prepared.settings, authority=Controller())
            run.wait(timeout=10)
            assert run.state is ContextState.FINISHED and run.records('dashboard_url')
    print(f'PASS installed wheel {jayrun.__version__}: {jayrun.__file__}; public exports, README, 15 examples, persistence, viewers, dashboard' + (' and YAML' if args.yaml else ''))


if __name__ == '__main__':
    main()
