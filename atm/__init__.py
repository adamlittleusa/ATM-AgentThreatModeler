"""ATM — Agent Threat Modeler.

A static collector and analysis harness for agent codebases.
The collector is deterministic and offline; it never executes or imports the
repository under audit.
"""

from .scan import ATM_VERSION, scan, write_inventory  # noqa: F401

__version__ = ATM_VERSION
