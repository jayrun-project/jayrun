# Encode portable values

Use public codecs for the values they define: `encode_configs` / `decode_configs` for configuration and `encode_record` / `decode_record` for structured context records. Both encode versioned portable representations and reject unsupported or over-limit input.

Configuration keeps exact immutable built-in types; record values permit their supported structured containers. Preserve false, zero, empty and None values according to the relevant contract. Decoding untrusted data must pass codec validation rather than invoking arbitrary constructors or pickle.

The [serialization reference](../../reference/serialization.md) lists signatures and bounds. For artifact entry/exit payloads, implement `BaseSerializer.serialize(value) -> bytes` and `deserialize(payload)` and [bind complete boundary coverage](../graphs/registration.md).

A whole `ContextSnapshot` contains more than config/record values: identities, ownership generations, requests, committed revisions, artifacts and other evidence. Neither codec pair is a whole-snapshot transport serializer. Your application must define the envelope, validate its peer and deliver it to an authorized Engine/runtime `apply` call.

Diagnostic persistence codecs are another boundary: they encode bounded evidence for inspection, not arbitrary executable objects or recoverable model state. Use application checkpoints for that purpose.
