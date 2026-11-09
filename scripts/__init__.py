"""Cluster qualification and development tools.

The standalone qualification tools use sibling imports. Keep their directory
available when a packaged development tool calls that existing harness.
"""
from pathlib import Path
import sys

_tools = str(Path(__file__).resolve().parent)
if _tools not in sys.path:
    sys.path.insert(0, _tools)
