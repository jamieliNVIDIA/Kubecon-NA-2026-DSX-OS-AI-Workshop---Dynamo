"""Shared repository paths and imports for standalone qualification tools.

Demo and test code uses explicit package imports. The qualification scripts
still use flat imports internally; expose their directory once for the suite.
"""
from pathlib import Path
import scripts  # Initialize standalone qualification imports in one place.

ROOT = Path(__file__).resolve().parents[1]
