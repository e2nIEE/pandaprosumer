"""
Data model for the electrical optimization element.
"""

import pandas as pd


class ElectricalOptimizationElementData:
    """Static data table of the electrical optimization element."""

    name = "electrical_optimization"

    input = pd.DataFrame(
        {
            "name": pd.Series(dtype="object"),
            "in_service": pd.Series(dtype="bool"),
        }
    )