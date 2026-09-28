"""Regenerate documentation HTML from runnable examples and the current viewer."""
from __future__ import annotations

from html import escape
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'docs' / '_examples'))

from jayrun import ArtifactContext, ConfigContext, Engine, GraphRegistry
from jayrun.context import ContextState
from jayrun.visualization import save
import first_graph
import conditional
import split_join
import validation
import lifetimes


def documentation_canvas(document: str) -> str:
    """Keep a fitted desktop overview in the manual's responsive landscape frame."""
    return ("<!doctype html><html><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>Jayrun documentation visualization</title><style>"
            "html,body{margin:0;width:100%;height:100%;overflow:hidden;background:transparent}"
            "iframe{position:absolute;left:0;top:0;width:1600px;height:1000px;border:0;transform-origin:0 0}"
            "</style></head><body><iframe title='Interactive Jayrun visualization' srcdoc=\""
            + escape(document, quote=True) + "\"></iframe><script>"
            + """
const frame = document.querySelector('iframe');
function resizeCanvas() {
    frame.style.transform = 'scale(' + Math.min(innerWidth / 1600, innerHeight / 1000) + ')';
}
frame.addEventListener('load', async () => {
    const win = frame.contentWindow;
    await win.customElements.whenDefined('jayrun-graph');
    if (!frame.isConnected || !frame.contentDocument) return;
    const graph = frame.contentDocument.querySelector('jayrun-graph');
    if (!graph) return;
    const fitGraph = () => win.requestAnimationFrame(() => {
        graph.fit();
        graph.dataset.documentationFitted = 'true';
    });
    // The normal viewer may initially prefer readable cards over an overview.
    // Documentation starts fitted; explicit zoom and Focus remain user-owned.
    win.requestAnimationFrame(fitGraph);
    graph.registrySelect?.addEventListener('change', fitGraph);
});
addEventListener('resize', resizeCanvas);
resizeCanvas();
</script></body></html>
""")


def main() -> None:
    destination = ROOT / 'docs' / '_static'
    destination.mkdir(exist_ok=True)
    outputs = ['split_join.html', 'conditional_routes.html', 'conditional_run.html',
               'plot_property_mismatch.html', 'first_graph.html', 'first_run.html',
               'lifetimes_graph.html', 'lifetimes_run.html']
    graph, source, result, scale = first_graph.build_graph()
    graph.plot.save(destination / 'first_graph.html')
    with Engine() as engine:
        run = engine.submit(graph, ArtifactContext({source: 7}),
                            ConfigContext({scale.factor: 3}))
        run.wait(timeout=5)
        assert run.state is ContextState.FINISHED
        assert run.artifact(result).value == 21
        payload = run.plot.build()
        payload['reiteration']['reason'] = 'This graph ran once and has no feedback artifact.'
        save(payload, destination / 'first_run.html')
    graph, _, _ = split_join.build_graph()
    graph.plot.save(destination / outputs[0])
    graph, left, right = conditional.build_graph(True)
    graph.plot.save(destination / outputs[1])
    with Engine() as engine:
        run = engine.submit(graph)
        run.wait(timeout=5)
        assert run.state is ContextState.FINISHED, run.report.data.failure
        assert (run.artifact(left).value, run.artifact(right).value) == (11, None)
        snapshot = run.plot.build()
        # This example has actual run evidence but no iteration-feedback edge.
        # Give the documentation export a specific structural hint instead of
        # the declaration adapter's generic "no execution evidence" wording.
        snapshot['reiteration']['reason'] = (
            'This graph has no feedback artifact. The captured run completed '
            'one iteration; its recorded step outcomes are shown.'
        )
        save(snapshot, destination / outputs[2])
    mismatch = validation.build_graph()
    assert not mismatch.validate().valid
    mismatch.plot.save(destination / outputs[3])
    graph, sample, result, calibration, scale = lifetimes.build_graph()
    graph.plot.save(destination / 'lifetimes_graph.html')
    with Engine() as engine:
        run = engine.submit(graph, ArtifactContext({sample: 3}),
                            ConfigContext({calibration.offset: 10, scale.factor: 2}))
        run.wait(timeout=5)
        assert run.state is ContextState.FINISHED
        assert run.artifact(result).value == 26
        assert tuple(r.value for r in run.records('calibration_loaded')) == (10,)
        payload = run.plot.build()
        payload['reiteration']['reason'] = 'This run completed one iteration; the graph has no feedback artifact.'
        save(payload, destination / 'lifetimes_run.html')
    registry = GraphRegistry()
    registry.register('scale', first_graph.build_graph()[0])
    registry.register('split-and-join', split_join.build_graph()[0])
    registry.plot.save(destination / 'registry.html')
    outputs.append('registry.html')
    for name in outputs:
        path = destination / name
        path.write_text(documentation_canvas(path.read_text()))
    # The dashboard is already a scaled landscape capture; do not wrap it twice.
    # Preserve the captured dashboard as the canonical published static asset.
    preview = destination / 'dashboard_preview.html'
    outputs.append('dashboard_preview.html')
    sources = [preview, Path(__file__).resolve(), *(ROOT / 'docs' / '_examples').glob('*.py'),
               *sorted((ROOT / 'jayrun' / 'visualization').rglob('*.py')),
               *sorted((ROOT / 'jayrun' / 'visualization').rglob('*.js')),
               *sorted((ROOT / 'jayrun' / 'visualization').rglob('*.css'))]
    manifest = {
        'generator': 'docs/_scripts/render_visualizations.py',
        'sources': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted(set(sources))},
        'outputs': {name: hashlib.sha256((destination / name).read_bytes()).hexdigest()
                    for name in outputs},
    }
    (destination / 'visualizations.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('Regenerated', ', '.join(outputs))


if __name__ == '__main__':
    main()
