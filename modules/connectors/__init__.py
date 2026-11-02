"""
Pakiet konektorów do oficjalnych API danych ekonomicznych (NBP, Eurostat, GUS).
"""

from modules.connectors.base import (
    BaseConnector,
    RawEvidence,
    MacroObservation,
    ConnectorException,
    DataNotFoundError,
    VariableNotMappedError,
    ValidationError,
    StaleDataError,
)
from modules.connectors.nbp import NbpConnector
from modules.connectors.eurostat import EurostatConnector
from modules.connectors.gus import GusConnector

__all__ = [
    "BaseConnector",
    "RawEvidence",
    "MacroObservation",
    "ConnectorException",
    "DataNotFoundError",
    "VariableNotMappedError",
    "ValidationError",
    "StaleDataError",
    "NbpConnector",
    "EurostatConnector",
    "GusConnector",
]
