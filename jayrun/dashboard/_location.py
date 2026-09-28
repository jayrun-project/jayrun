"""Detached execution provenance, not physical host discovery or authority."""
from __future__ import annotations

from hashlib import sha256


def execution_location(engine_id: str | None, *, local_engine_id: str | None = None,
                       local_name: str | None = None) -> dict[str, str | bool | None]:
    """Keep engine incarnation, host and capture partition semantically separate.

    Snapshot.engine_id is a routing owner identity. Only the observing runtime can
    supply its own verified name; remote names and physical hosts remain unknown.
    A bounded label never becomes an identity: grouping uses the full value hash.
    """
    if not engine_id:
        return {'id': 'unknown', 'engine_id': None, 'engine_name': None,
                'physical_machine': None, 'identity_omitted': False,
                'provenance': 'Execution owner was not captured'}
    return {'id': sha256(engine_id.encode('utf-8', errors='surrogatepass')).hexdigest(),
            'engine_id': engine_id[:256],
            'engine_name': local_name[:256] if engine_id == local_engine_id and local_name else None,
            'physical_machine': None, 'identity_omitted': len(engine_id) > 256,
            'provenance': 'Captured engine incarnation (routing owner); physical host unknown'}
