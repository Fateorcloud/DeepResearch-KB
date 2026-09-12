**Internal decisions (Boreal)**
- Current architecture v2—marked synthetic evaluation data, not actual production documentation—uses SQLite for metadata and approves a deployment budget of one writer ([architecture-v2.txt](architecture-v2.txt)).
- Version 1 is deprecated and superseded; it previously used PostgreSQL with eight concurrent writers and must not be used as current design ([architecture-v1.txt](architecture-v1.txt)).

**External capabilities (SQLite)**
- SQLite is an in-process, self-contained, serverless, zero-configuration, embedded SQL engine with no separate server process ([SQLite About](https://sqlite.org/about.html)).
- WAL allows concurrent readers/writers, but all processes must be on the same host; WAL does not work over a network filesystem ([SQLite WAL](https://sqlite.org/wal.html)).

**Combining**
- Boreal’s current metadata engine is SQLite with one approved writer ([architecture-v2.txt](architecture-v2.txt)); SQLite externally is serverless/embedded ([SQLite About](https://sqlite.org/about.html)); WAL externally has same-host and no-network-filesystem limits ([SQLite WAL](https://sqlite.org/wal.html)).
