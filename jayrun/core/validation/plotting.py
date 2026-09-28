"""Compatibility import for the declaration plotting adapter.

The static renderer lives in jayrun.visualization and does not import this module.
"""
from ...visualization.adapters.definition import GraphPlotter

__all__ = ("GraphPlotter",)
