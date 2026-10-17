"""The SQLite storage layer: connections, schema migrations and typed queries.

Repository functions take a connection from :mod:`monelyth_engine.db.connection` and return
the dataclasses in :mod:`monelyth_engine.db.models`, so callers never handle raw rows.
"""
