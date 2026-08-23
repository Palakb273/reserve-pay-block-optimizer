"""Closed Phase 1 domain vocabularies."""

from enum import StrEnum


class Currency(StrEnum):
    INR = "INR"


class TransactionDomain(StrEnum):
    MOBILITY = "mobility"


class SupportedCity(StrEnum):
    DELHI = "delhi"
    MUMBAI = "mumbai"
    BENGALURU = "bengaluru"
    HYDERABAD = "hyderabad"
    PUNE = "pune"
    CHENNAI = "chennai"
    KOLKATA = "kolkata"

