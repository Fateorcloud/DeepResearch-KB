**Internal decisions (Boreal)**
- Current Boreal architecture v2 uses SQLite for metadata and approves a one-writer deployment budget; v1 is replaced. [Boreal architecture v2](kb://832e6f3aae9b4100abbd9270a450a167/versions/2/chunks/d38f573f983e41c7ada09be269818ee7)
- The Boreal office document is administrative only and does not describe database architecture. [Boreal office](kb://ad7282e7e5234b7f9e21e67881e2908d/versions/1/chunks/699240a1bf3647d8aeac9395378707a1)

**External SQLite facts**
- SQLite is an in-process, serverless, zero-configuration, transactional SQL engine; it is embedded and has no separate server process. [SQLite About](https://sqlite.org/about.html)
- WAL allows concurrent readers/writers, but all processes using the database must be on the same host; WAL does not work over a network filesystem. [SQLite WAL](https://sqlite.org/wal.html)

**Combined**
- Boreal's SQLite metadata choice and one-writer budget are internal decisions; SQLite's serverless model and WAL network-filesystem limitation are external capabilities/constraints. [Boreal architecture v2](kb://832e6f3aae9b4100abbd9270a450a167/versions/2/chunks/d38f573f983e41c7ada09be269818ee7); [SQLite About](https://sqlite.org/about.html); [SQLite WAL](https://sqlite.org/wal.html)
- No supplied Boreal source states whether Boreal uses WAL or a network filesystem; that is unavailable. [Boreal architecture v2](kb://832e6f3aae9b4100abbd9270a450a167/versions/2/chunks/d38f573f983e41c7ada09be269818ee7); [Boreal office](kb://ad7282e7e5234b7f9e21e67881e2908d/versions/1/chunks/699240a1bf3647d8aeac9395378707a1)
