"""
Coupling of a DHN substation to the network's supply: the temperature only.

`NetworkCouplingControl` hands the substation the mass flow of the latest network solve together with the
supply temperature. The heat exchanger takes a supplied flow as given: what it does not need bypasses the
exchanger and returns hot, and the same total flow is written back into the heat consumer, so the initial flow
of the JSON (`initialMassFlowkgpers`) reproduces itself step after step whatever the demand (10 kg/s and
returns at 78-84 °C in the game, for 30-500 kW demands).

Here the substation only learns at what temperature the network arrives. Its mass flow comes from its own
demand chain (heat demand -> exchanger, `t_m_to_deliver`), exactly as for an exchanger fed by a constant
profile, and the writing coupling puts that flow into the heat consumer. Flows follow the demand, and the
return temperature is the exchanger's, not a hot bypass.
"""
import numpy as np

from pandaprosumer.constants import CELSIUS_TO_K
from pandaprosumer.energy_system.control.controller.coupling.network_coupling import NetworkCouplingControl
from pandaprosumer.mapping import FluidMixMapping


class SubstationSupplyCouplingControl(NetworkCouplingControl):
    """Hands the network's supply temperature at a heat consumer to the substation, with no mass flow."""

    def __init__(self, net, *args, n_outputs=1, **kwargs):
        super().__init__(net, *args, **kwargs)
        if self.temp_fluid_map_output_idx is None or self.temp_fluid_map_output_idx >= len(self.result_columns):
            raise ValueError(f"SubstationSupplyCouplingControl {self.name}: temp_fluid_map_output_idx "
                             f"({self.temp_fluid_map_output_idx}) must index result_columns {self.result_columns}")
        if n_outputs < 1:
            raise ValueError(f"SubstationSupplyCouplingControl {self.name}: n_outputs must be >= 1, got {n_outputs}")
        self.n_outputs = n_outputs

    def _fluid_mix_outputs(self, results):
        """The supply temperature for every fed element; the mass flow is left to the element (NaN)."""
        t_supply_c = float(results[0][self.temp_fluid_map_output_idx]) - CELSIUS_TO_K
        return [{FluidMixMapping.TEMPERATURE_KEY: t_supply_c, FluidMixMapping.MASS_FLOW_KEY: np.nan}
                for _ in range(self.n_outputs)]
