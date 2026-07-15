"""
Test edge cases for gas boiler and electric boiler maximum temperature constraints.
Specifically tests the case where t_in_c > max_t_out_c.
"""

import numpy as np
from pandaprosumer.controller.models.gas_boiler import _calculate_gas_boiler_temp
from pandaprosumer.controller.models.electric_boiler import _calculate_electric_boiler_temp


class TestBoilerMaxTOutEdgeCase:
    """Test edge cases for boiler maximum temperature constraints."""
