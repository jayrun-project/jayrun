# Portable value codecs

These codecs encode config/record values, not entire context snapshots or arbitrary artifacts. Consult [portable values](../guides/integration/values.md) for transport boundaries and [configuration](../guides/graphs/configuration.md) for exact types.

```{eval-rst}
.. autofunction:: jayrun.serialization.encode_configs
```

```{eval-rst}
.. autofunction:: jayrun.serialization.decode_configs
```

```{eval-rst}
.. autofunction:: jayrun.serialization.encode_record
```

```{eval-rst}
.. autofunction:: jayrun.serialization.decode_record
```
