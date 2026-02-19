"""
DEPRECATED — use ``channels.base.BaseChannel`` instead.

This module is kept for reference only.  The ``BaseChannel`` abstract class
in ``channels/base.py`` provides the same contract with a richer interface
(connect, disconnect, broadcast, scoped send).

Migration:
    Old:  ``from core.integrations import IntegrationBase``
    New:  ``from channels.base import BaseChannel``
"""

from __future__ import annotations

import warnings

from channels.base import BaseChannel

warnings.warn(
    "core.integrations is deprecated — use channels.base.BaseChannel instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export for backward compat
IntegrationBase = BaseChannel

__all__ = ["IntegrationBase"]
