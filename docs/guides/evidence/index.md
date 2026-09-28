# Records, observation and persistence

The previous chapter explains how to [read reports and visualize results](plots.md). This chapter explains how evidence is produced, observed and retained: application records, progress samples, live events, terminal summaries and stored history. Start with records and live observation, then use **Persistence and Database** to attach storage with `Engine(database=...)`, read completed runs after shutdown and configure retention. Runtime history access follows database setup because it explains how components receive permission to read that store.

```{toctree}
:maxdepth: 1

../../model/evidence
records
progress
persistence
../runtime/history
```
