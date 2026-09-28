"""Explicitly enabled, independent persistence; importing this module performs no I/O.

Database may be owned by an Engine for finalized context and engine-session
history and timing profiles, or opened read-only for standalone inspection.
Legacy conversion is explicit; importing storage changes no runtime behavior.
"""
from ._database import Database, DatabaseReader, DatabaseStatus
from .backend import Backend
from .legacy import import_legacy
from .errors import (PersistenceBackpressure, PersistenceError, PersistenceFlushError,
                     PersistenceTimeout, StorageContractError, StorageUnavailable)
from .policy import DatabaseLimits, RetentionPolicy
from .records import (ContextHistoryEntry, ContextHistoryHeader, EngineSessionHeader,
                      EngineSessionRecord, HistoryPage, HistoryQuery, SerializedLayout,
                      SessionQuery, LegacyImportRecord)
from .values import (DiagnosticCodec, ValueLimits, ValueMarker, ValueSnapshot, encode_value)

__all__ = [
    "Database", "DatabaseReader", "DatabaseStatus", "Backend", "DatabaseLimits", "RetentionPolicy",
    "ContextHistoryEntry", "ContextHistoryHeader", "EngineSessionRecord", "EngineSessionHeader",
    "HistoryQuery", "SessionQuery", "HistoryPage", "SerializedLayout", "DiagnosticCodec",
    "ValueLimits", "ValueMarker", "ValueSnapshot", "encode_value", "PersistenceError",
    "StorageContractError", "StorageUnavailable", "PersistenceBackpressure", "PersistenceTimeout",
    "PersistenceFlushError", "LegacyImportRecord", "import_legacy",
]
