# Validate and inspect a graph

Graph construction checks structure. Property validation compares declared input/output requirements; confirmation prepares a usable graph. None of these proves arbitrary application payload correctness.

Use `graph.inspect` for graph-local artifact/config/resource definitions, `graph.validate()` for a validation report, `graph.report` for textual reporting and `graph.plot` for a portable interactive view. Inspection does not execute operators.

## A known mismatch

This complete example constructs a graph whose producer declares `str` while its consumer requires `int`. Construction succeeds; confirmation raises `ValueError` because the static mismatch is known.

```{literalinclude} ../../_examples/validation.py
:language: python
```

In the embedded visualization, open **Issues** and select the mismatched relationship. The incompatible type requirement is visible on the producer–consumer relationship. Correct it by using a compatible producer or by inserting an explicit conversion operator with accurate input/output properties. Deleting metadata merely hides the diagnostic.

```{raw} html
<iframe class="graph-viewer" src="../../_static/plot_property_mismatch.html" title="A string producer connected to an integer consumer" loading="lazy" allowfullscreen></iframe>
```

## Unknown compatibility

Missing metadata is not a proven mismatch, nor proof that a payload will work. Shape dimensions with unknown values and properties with incomplete information must be interpreted through the validation status, not reduced to a Boolean success claim. Library/device behavior still needs execution tests.

For a constructed graph, save a view with `graph.plot.save("graph.html")`. A declaration view shows topology and contracts. A run view shows captured execution evidence; it is not interchangeable with validation. See [visualization and reporting](../evidence/plots.md).

The [inspection reference](../../reference/inspection.md) documents returned views and validation statuses. For construction failures before a graph exists, start with [graph resolutions](resolutions.md).
