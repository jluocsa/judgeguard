from .authorized_sources import authorized_sources
from .citation_resolvable import citation_resolvable
from .injection_resistance import injection_resistance
from .leakage import leakage
from .loop_termination import loop_termination

DEFAULT_CHECKS = [
    citation_resolvable,
    authorized_sources,
    loop_termination,
    leakage,
    injection_resistance,
]

__all__ = [
    "DEFAULT_CHECKS",
    "authorized_sources",
    "citation_resolvable",
    "injection_resistance",
    "leakage",
    "loop_termination",
]
