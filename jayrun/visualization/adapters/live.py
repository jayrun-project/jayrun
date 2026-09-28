"""Public run observations adapted to the existing checked progress renderer."""
from __future__ import annotations


def live_payload(run) -> dict:
    snapshot = run.snapshot()
    plotter = run.graph.plot
    graph = plotter.build(mode='dashboard')
    progress = plotter.progress_data(snapshot.progress)
    return {'graph':graph, 'observation':{
        'graph_id':progress['graph_id'], 'context_id':str(snapshot.context_id),
        'generation':snapshot.generation, 'revision':snapshot.revision,
        'sample':snapshot.progress.observed_at.isoformat(), 'progress':progress}}
