"""Run with python -I after installing a wheel; never import checkout code."""
from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
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
        from jayrun import Artifact, ArtifactFlow, BaseOperator, GraphDefinition
        from jayrun.settings import ContextSettings, ControllerPolicy, EngineSettings
        from runtime_control import Answer
        answer = Artifact(name='answer')
        delegated = GraphDefinition(ArtifactFlow(Answer(outputs=(answer,))),
                                   name='Installed declaration', description='Purpose ' * 1500)
        delegated.confirm()
        declaration = delegated.report.to_json()
        assert json.loads(declaration) == delegated.report.to_dict()
        assert json.loads(declaration)['schema'] == 'jayrun.declaration/1'
        assert delegated.plot.build()['declaration_report_json'] == declaration
        assert delegated.plot.build()['description'] == delegated.description
        assert 'Export declaration report' in delegated.plot.to_html()

        class SubmitController(BaseOperator):
            def __init__(self):
                super().__init__()
                self.outputs = ()

            async def execute(self):
                child = self.runtime.submit(delegated,
                                            settings=ContextSettings(max_iterations=1),
                                            authority=Controller())
                await child.wait_async(timeout=10)
                assert child.state is ContextState.FINISHED, child.report.data.failure
                self.context.record('child_answer', child.artifact(answer).value)
                return ()

        parent = GraphDefinition(ArtifactFlow(SubmitController()))
        parent.confirm()
        with Engine(EngineSettings(controller_policy=ControllerPolicy.DELEGATED)) as engine:
            run = engine.submit(parent, authority=Controller())
            run.wait(timeout=10)
            assert run.state is ContextState.FINISHED, run.report.data.failure
            assert run.records('child_answer')[0].value == 42
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
    print(f'PASS installed wheel {jayrun.__version__}: {jayrun.__file__}; public exports, README, 15 examples, persistence, viewers, dashboard, declaration reports and delegated submission' + (' and YAML' if args.yaml else ''))


if __name__ == '__main__':
    main()
