"""Capture a result, read it after shutdown, and walk bounded history pages."""
from pathlib import Path
from tempfile import TemporaryDirectory
from jayrun import ArtifactContext, ConfigContext, Engine
from jayrun.context import ContextState
from jayrun.persistence import Database, HistoryQuery
from first_graph import build_graph


def main():
    graph, source, result, scale = build_graph()
    with TemporaryDirectory() as directory:
        path = Path(directory) / "history.sqlite"
        with Engine(database=Database(path)) as engine:
            run = engine.submit(graph, ArtifactContext({source: 7}),
                                ConfigContext({scale.factor: 3}))
            run.wait(timeout=5)
            assert run.state is ContextState.FINISHED, run.report.data.failure
            engine.database.flush(timeout=5)
        with Database(path) as history:
            sessions = history.query_sessions()
            session = sessions.items[0]
            reader = history.reader(session_ids=(session.session_id,))
            cursor = None
            found = []
            while True:
                page = reader.query_contexts(HistoryQuery(limit=10, cursor=cursor))
                for header in page.items:
                    detail = reader.get_context(header.session_id, header.context_id)
                    assert detail is not None
                    found.append(header)
                    print(header.outcome)
                cursor = page.next_cursor
                if cursor is None:
                    break
            assert len(found) == 1 and found[0].outcome == "finished"


if __name__ == "__main__":
    main()
