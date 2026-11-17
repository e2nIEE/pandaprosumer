"""
Coupling of a DHN plant to the network's circulation pump that conserves the plant's heat.

The circulation pump is the network's slack: it moves whatever flow the substations draw, at the supply
temperature written into `t_flow_k`. `NetworkCouplingControl` writes the temperature of the water the plant
heated. When the plant heats only part of the flow (a boiler at its maximum power), the pump still sent ALL
the flow out at that temperature, and the heat of the part the plant did not heat came from nowhere.

Here the pump injects the heat the plant produced, no more: the flow the plant does not take passes it at
return temperature (a plant bypass), and the supply temperature is

    t_flow = min(t_return + Q_plant / (mdot_network * cp), t_plant)

capped at the temperature of the water the plant delivers: the network cannot be heated above its hottest
source. A plant making more heat than the network flow can take (an electricity-led CHP in a mild hour) dumps
the surplus, which shows as plant heat above the pump's heat.

The colder supply may change the return temperature in the same step (short networks bring the water back
within the hour), so the supply temperature is iterated with the network solve (the controller stays
unconverged, which makes the control loop solve the network again) until both agree. The plant itself is
not run again: its heat for the step is fixed, so stateful elements such as storages are not stepped twice.

The plant is always asked for the network's supply setpoint (the pump's `t_flow_k` at creation), not for the
supply temperature of the latest solve: after a short step that one is the lower mixed temperature, and the
target would ratchet down step after step. The network itself keeps the supply temperature it really had, so
the return temperature the plant heats from is as close as possible to the one of the final solve.
"""

import logging

import numpy as np

from pandaprosumer.constants import CELSIUS_TO_K
from pandaprosumer.energy_system.control.controller.coupling.network_coupling import NetworkCouplingControl
from pandaprosumer.mapping import FluidMixMapping

logger = logging.getLogger(__name__)

# The supply temperature is settled when an iteration moves it by less than this.
SUPPLY_TEMPERATURE_TOLERANCE_K = 1e-3
MAX_SUPPLY_ITERATIONS = 20
MIN_SECANT_SLOPE = 1e-6  # below it the secant step is unreliable: plain substitution instead


def plant_heat_w(mdot_plant_kg_per_s, t_plant_k, t_inlet_k, cp_j_per_kgk):
    """Heat the plant gave the water it took in. A plant that delivered nothing (NaN or no flow) gives 0."""
    if np.isnan(mdot_plant_kg_per_s) or np.isnan(t_plant_k) or mdot_plant_kg_per_s <= 0:
        return 0.0
    return mdot_plant_kg_per_s * cp_j_per_kgk * (t_plant_k - t_inlet_k)


def supply_temperature_k(heat_w, mdot_network_kg_per_s, t_return_k, cp_j_per_kgk, t_plant_k=np.nan):
    """
    Supply temperature of the network flow once the pump gave it `heat_w` (no flow: the return temperature),
    at most the plant's outlet temperature `t_plant_k` when the plant heats (NaN: no cap).
    """
    if mdot_network_kg_per_s <= 0:
        return t_return_k
    t_supply_k = t_return_k + heat_w / (mdot_network_kg_per_s * cp_j_per_kgk)
    if heat_w > 0 and not np.isnan(t_plant_k):
        t_supply_k = min(t_supply_k, max(t_plant_k, t_return_k))
    return t_supply_k


class PlantPumpCouplingControl(NetworkCouplingControl):
    """Writes the plant's heat into the circulation pump as a supply temperature, settled with the network."""

    def __init__(self, net, *args, **kwargs):
        super().__init__(net, *args, **kwargs)
        self.setpoint_k = float(net[self.element_name].at[self.element_index[0], "t_flow_k"])
        self._reset_step()

    def _reset_step(self):
        self.heat_w = None
        self.t_plant_k = np.nan
        self.settled = False
        self.iterations = 0
        self.previous = None  # (supply temperature solved, its residual) of the previous iteration

    def time_step(self, net, time):
        """Start a step: the plant's heat and the supply temperature are settled anew."""
        super().time_step(net, time)
        self._reset_step()

    def _t_m_to_receive_init(self, net):
        """What the plant must deliver: the setpoint supply temperature, on the network's return flow."""
        _, t_return_c, mdot_kg_per_s = super()._t_m_to_receive_init(net)
        return np.full_like(t_return_c, self.setpoint_k - CELSIUS_TO_K), t_return_c, mdot_kg_per_s

    def is_converged(self, net):
        """Converged once applied AND the supply temperature agrees with the network solve."""
        return super().is_converged(net) and self.settled

    def _pump_result(self, net):
        result = net["res_" + self.element_name].loc[self.element_index[0]]
        return float(result["mdot_from_kg_per_s"]), float(result["t_from_k"])

    def _set_supply(self, net, t_flow_k):
        net[self.element_name].at[self.element_index[0], "t_flow_k"] = t_flow_k

    def control_step(self, net):
        """Fix the plant's heat on the first pass, then move the supply temperature towards the network's answer."""
        def cp(t_k):
            return float(net.fluid.get_heat_capacity(t_k))

        # supply temperature the latest network solve used
        solved_k = float(net[self.element_name].at[self.element_index[0], "t_flow_k"])
        if self.heat_w is None:
            # First pass: the plant just ran on the flow and return temperature of the latest solve.
            delivered = self.input_mass_flow_with_temp
            super().control_step(net)
            _, t_inlet_k = self._pump_result(net)
            t_plant_k = float(delivered[FluidMixMapping.TEMPERATURE_KEY]) + CELSIUS_TO_K
            self.t_plant_k = t_plant_k
            t_mean_k = t_inlet_k if np.isnan(t_plant_k) else (t_plant_k + t_inlet_k) / 2
            self.heat_w = plant_heat_w(float(delivered[FluidMixMapping.MASS_FLOW_KEY]), t_plant_k, t_inlet_k,
                                       cp(t_mean_k))
        mdot_kg_per_s, t_return_k = self._pump_result(net)
        first_guess_k = supply_temperature_k(self.heat_w, mdot_kg_per_s, t_return_k, cp(t_return_k), self.t_plant_k)
        target_k = supply_temperature_k(self.heat_w, mdot_kg_per_s, t_return_k, cp((t_return_k + first_guess_k) / 2),
                                        self.t_plant_k)
        residual_k = solved_k - target_k
        self.iterations += 1
        if abs(residual_k) < SUPPLY_TEMPERATURE_TOLERANCE_K:
            self.settled = True
            self._set_supply(net, solved_k)  # keep the solved network: no further solve
            return
        # The return temperature follows the supply temperature within the step: solve
        # supply - target(supply) = 0 by secant steps (a plain substitution converges slowly on short networks).
        next_k = target_k
        if self.previous is not None:
            previous_k, previous_residual_k = self.previous
            slope = (residual_k - previous_residual_k) / (solved_k - previous_k) if solved_k != previous_k else 0.0
            if abs(slope) > MIN_SECANT_SLOPE:
                next_k = solved_k - residual_k / slope
        self.previous = (solved_k, residual_k)
        if self.iterations >= MAX_SUPPLY_ITERATIONS:
            logger.warning("%s: supply temperature not settled after %d iterations (residual %.4f K)",
                           self.name, self.iterations, residual_k)
            self.settled = True
        self._set_supply(net, next_k)
