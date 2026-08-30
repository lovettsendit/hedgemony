"""hedgemony -- find the things an AI made up.

A fabrication is a claim about the world that is false: a package that was never published, a
method that does not exist, a call that cannot be made. Every check here is decided by the
interpreter or by a package registry, never by a language model, so a finding is a fact rather
than a confidence score.
"""
__version__ = "1.0.0"

from .scan import scan, FabricationClass          # noqa: F401
from .contracts import check_contracts            # noqa: F401
from .sandbox import Limits, DEFAULT_LIMITS       # noqa: F401

__all__ = ["scan", "check_contracts", "Limits", "DEFAULT_LIMITS", "FabricationClass",
           "__version__"]
