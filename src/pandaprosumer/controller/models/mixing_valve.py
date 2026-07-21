"""
Module containing the MixingValveController class.
"""

import logging
import numpy as np

from pandaprosumer.controller.base import BasicProsumerController
from pandaprosumer.constants import CELSIUS_TO_K, TEMPERATURE_CONVERGENCE_THRESHOLD_C
from pandaprosumer.mapping import FluidMixMapping

logger = logging.getLogger(__name__)


class MixingValveController(BasicProsumerController):
    """
    Controller for a 3-way mixing valve.

    The valve draws hot fluid at t_in_c from an upstream producer (FluidMix
    initiator) and mixes it with return fluid recirculated at the responders'
    return temperature, so the responders receive their wished feed
    temperature. Mass and energy are conserved exactly under the constant-cp
    mixing rule (cp evaluated at the mean temperature; no heat loss, no
    pressure modeling).

    :param prosumer: The prosumer object
    :param mixing_valve_object: The mixing valve controller data object
    :param order: The order of the controller
    :param level: The level of the controller
    :param in_service: The in-service status of the controller
    :param index: The index of the controller
    :param kwargs: Additional keyword arguments
    """

    def name_class(self):
        return "mixing_valve_controller"

    def __init__(self, prosumer, mixing_valve_object, order, level,
                 in_service=True, index=None, name=None, **kwargs):
        """
        Constructor method
        """
        super().__init__(prosumer, mixing_valve_object, order=order, level=level, in_service=in_service,
                         index=index, name=name, **kwargs)
        self.t_previous_in_c = np.nan
        self.t_previous_return_c = np.nan
        self.mdot_previous_in_kg_per_s = np.nan

    @property
    def _t_received_c(self):
        """Supply temperature received from the upstream FluidMix, or NaN."""
        return self.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY]

    @property
    def _mdot_received_kg_per_s(self):
        """Mass flow fixed by the upstream FluidMix initiator, or NaN if free."""
        return self.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY]

    def calculate_mixing(self, t_in_c, t_out_req_c, t_return_req_c, mdot_out_req_kg_per_s):
        """
        Mixing algebra of the 3-way valve for a free (non-fixed) hot-leg flow.

        :param t_in_c: The hot supply temperature [°C]
        :param t_out_req_c: The feed temperature wished by the responders [°C]
        :param t_return_req_c: The responders' return temperature [°C]
        :param mdot_out_req_kg_per_s: The total mass flow required by the responders [kg/s]
        :return: A tuple (hot-leg mass flow [kg/s], recirculated mass flow [kg/s],
            delivered mass flow [kg/s], delivered feed temperature [°C])
        """
        if mdot_out_req_kg_per_s < 1e-6 or (t_out_req_c - t_return_req_c) < 1e-3:
            # Degenerate demand: nothing to deliver
            return 0., 0., 0., t_in_c
        if (t_in_c - t_return_req_c) < 1e-3:
            # Dead supply: cannot heat the return at all
            return 0., 0., 0., t_in_c
        if t_in_c <= t_out_req_c:
            # Cold supply: fully open, pass the flow through unchanged
            return mdot_out_req_kg_per_s, 0., mdot_out_req_kg_per_s, t_in_c
        mdot_in_kg_per_s = (mdot_out_req_kg_per_s
                            * (t_out_req_c - t_return_req_c) / (t_in_c - t_return_req_c))
        mdot_recirc_kg_per_s = mdot_out_req_kg_per_s - mdot_in_kg_per_s
        return mdot_in_kg_per_s, mdot_recirc_kg_per_s, mdot_out_req_kg_per_s, t_out_req_c

    def _t_m_to_receive_init(self, prosumer):
        """
        Return the expected received Feed temperature, return temperature and mass flow in °C and kg/s

        :param prosumer: The prosumer object
        :return: A Tuple (Feed temperature, return temperature and mass flow)
        """
        if not np.isnan(self.t_previous_return_c):
            return self.t_previous_in_c, self.t_previous_return_c, self.mdot_previous_in_kg_per_s
        t_in_nom_c = self._get_element_param(prosumer, 't_in_nom_c')
        return self.t_m_to_receive_for_t(prosumer, t_in_nom_c)

    def t_m_to_receive_for_t(self, prosumer, t_feed_c):
        """
        For a given feed temperature in °C, calculate the required feed mass flow
        and the expected return temperature if this feed temperature is provided.

        :param prosumer: The prosumer object
        :param t_feed_c: The feed temperature
        :return: A Tuple (Feed temperature, return temperature and mass flow)
        """
        t_out_req_c, t_return_req_c, mdot_tab_req_kg_per_s = self.t_m_to_deliver(prosumer)
        mdot_out_req_kg_per_s = sum(mdot_tab_req_kg_per_s)
        mdot_in_kg_per_s, _, _, _ = self.calculate_mixing(t_feed_c, t_out_req_c,
                                                          t_return_req_c, mdot_out_req_kg_per_s)
        return t_feed_c, t_return_req_c, mdot_in_kg_per_s

    def _save_state(self):
        """Backup states before Run"""
        self._backup_state = {
            "t_previous_in_c": self.t_previous_in_c,
            "t_previous_return_c": self.t_previous_return_c,
            "mdot_previous_in_kg_per_s": self.mdot_previous_in_kg_per_s,
        }

    def _restore_state(self):
        """Restore states before Rerun"""
        if hasattr(self, "_backup_state"):
            self.t_previous_in_c = self._backup_state["t_previous_in_c"]
            self.t_previous_return_c = self._backup_state["t_previous_return_c"]
            self.mdot_previous_in_kg_per_s = self._backup_state["mdot_previous_in_kg_per_s"]

    def control_step(self, prosumer):
        """
        Executes the control step for the controller.

        :param prosumer: The prosumer object
        """
        if not prosumer.rerun:
            self._save_state()
        else:
            self._restore_state()

        if not (self.in_service and getattr(prosumer, self.obj.element_name).iloc[
                self.obj.element_index[0]].in_service):
            self.applied = True
            return

        super().control_step(prosumer)

        if not self._are_initiators_converged(prosumer):
            # If some of the initiators are not converged, do not run the control step
            self._unapply_initiators(prosumer)
            self.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: np.nan,
                                              FluidMixMapping.MASS_FLOW_KEY: np.nan}
            return

        t_out_req_c, t_return_req_c, mdot_tab_req_kg_per_s = self.t_m_to_deliver(prosumer)
        mdot_out_req_kg_per_s = sum(mdot_tab_req_kg_per_s)

        t_in_c = self._t_received_c
        if np.isnan(t_in_c):
            t_in_c = self._get_element_param(prosumer, 't_in_nom_c')

        assert not np.isnan(t_out_req_c), \
            f"Mixing Valve {self.name} t_out_req_c is NaN for timestep {self.time} in prosumer {prosumer.name}"
        assert not np.isnan(t_return_req_c), \
            f"Mixing Valve {self.name} t_return_req_c is NaN for timestep {self.time} in prosumer {prosumer.name}"
        assert not np.isnan(mdot_out_req_kg_per_s), \
            f"Mixing Valve {self.name} mdot_out_req_kg_per_s is NaN for timestep {self.time} in prosumer {prosumer.name}"

        (mdot_in_kg_per_s, mdot_recirc_kg_per_s,
         mdot_out_kg_per_s, t_out_c) = self.calculate_mixing(t_in_c, t_out_req_c,
                                                             t_return_req_c, mdot_out_req_kg_per_s)

        mdot_received_kg_per_s = self._mdot_received_kg_per_s
        if not np.isnan(mdot_received_kg_per_s) and mdot_out_kg_per_s > 1e-9:
            assert mdot_received_kg_per_s >= 0, \
                (f"Mixing Valve {self.name} received mass flow is negative for timestep {self.time} "
                 f"in prosumer {prosumer.name}")
            if t_in_c <= t_out_req_c:
                # Cold supply: pass through whatever arrives, never recirculate to top up
                mdot_in_kg_per_s = mdot_received_kg_per_s
                mdot_recirc_kg_per_s = 0.
                mdot_out_kg_per_s = mdot_received_kg_per_s
                t_out_c = t_in_c
            elif mdot_received_kg_per_s >= mdot_out_req_kg_per_s:
                # Flooded: no recirculation, everything passes through at t_in_c;
                # the mass surplus is dispatched per overflow_strategy below
                mdot_in_kg_per_s = mdot_received_kg_per_s
                mdot_recirc_kg_per_s = 0.
                mdot_out_kg_per_s = mdot_received_kg_per_s
                t_out_c = t_in_c
            elif mdot_received_kg_per_s > mdot_in_kg_per_s:
                # Excess hot flow: recirculation shrinks, the mix runs hotter than target
                mdot_in_kg_per_s = mdot_received_kg_per_s
                mdot_recirc_kg_per_s = mdot_out_req_kg_per_s - mdot_received_kg_per_s
                mdot_out_kg_per_s = mdot_out_req_kg_per_s
                t_out_c = ((mdot_in_kg_per_s * t_in_c + mdot_recirc_kg_per_s * t_return_req_c)
                           / mdot_out_kg_per_s)
            elif mdot_received_kg_per_s < mdot_in_kg_per_s:
                # Short supply: hold the wished feed temperature, scale the delivered flow down
                mdot_in_kg_per_s = mdot_received_kg_per_s
                mdot_out_kg_per_s = (mdot_received_kg_per_s
                                     * (t_in_c - t_return_req_c) / (t_out_req_c - t_return_req_c))
                mdot_recirc_kg_per_s = mdot_out_kg_per_s - mdot_in_kg_per_s
                t_out_c = t_out_req_c

        overflow_strategy = self._get_element_param(prosumer, 'overflow_strategy')
        if overflow_strategy is None or (isinstance(overflow_strategy, float) and np.isnan(overflow_strategy)):
            overflow_strategy = "cap"
        result_mdot_tab_kg_per_s = self._merit_order_mass_flow(prosumer, mdot_out_kg_per_s,
                                                               mdot_tab_req_kg_per_s,
                                                               overflow_strategy)

        if len(self._get_mapped_responders(prosumer)) > 1 and mdot_out_kg_per_s < mdot_out_req_kg_per_s:
            # If the valve cannot deliver the required mass flow, recalculate the return
            # temperature, considering that all the downstream elements will still return
            # the same temperature even with a lower delivered mass flow
            t_return_tab_c = self.get_treturn_tab_c(prosumer)
            if abs(mdot_out_kg_per_s) > 1e-8:
                t_return_new_c = np.sum(np.array(result_mdot_tab_kg_per_s) * t_return_tab_c) / mdot_out_kg_per_s
                if abs(t_return_new_c - t_return_req_c) > 1:
                    t_return_req_c = t_return_new_c

        cp_kj_per_kgk = prosumer.fluid.get_heat_capacity(
            CELSIUS_TO_K + (t_out_c + t_return_req_c) / 2) / 1000
        q_delivered_kw = mdot_out_kg_per_s * cp_kj_per_kgk * (t_out_c - t_return_req_c)

        assert mdot_in_kg_per_s >= 0, \
            f"Mixing Valve {self.name} mdot_in_kg_per_s is negative ({mdot_in_kg_per_s}) for timestep {self.time}"
        assert mdot_recirc_kg_per_s >= -1e-9, \
            f"Mixing Valve {self.name} mdot_recirc_kg_per_s is negative ({mdot_recirc_kg_per_s}) for timestep {self.time}"
        assert abs(mdot_in_kg_per_s + mdot_recirc_kg_per_s - mdot_out_kg_per_s) < 1e-6, \
            (f"Mixing Valve {self.name} mass balance violated "
             f"({mdot_in_kg_per_s} + {mdot_recirc_kg_per_s} != {mdot_out_kg_per_s}) for timestep {self.time}")

        result = np.array([[q_delivered_kw, mdot_in_kg_per_s, t_in_c,
                            mdot_recirc_kg_per_s, mdot_out_kg_per_s, t_out_c, t_return_req_c]])

        result_fluid_mix = []
        for mdot_kg_per_s in result_mdot_tab_kg_per_s:
            result_fluid_mix.append({FluidMixMapping.TEMPERATURE_KEY: t_out_c,
                                     FluidMixMapping.MASS_FLOW_KEY: mdot_kg_per_s})

        if (np.isnan(self.t_keep_return_c) or mdot_in_kg_per_s == 0
                or abs(t_return_req_c - self.t_keep_return_c) < TEMPERATURE_CONVERGENCE_THRESHOLD_C):
            self._check_fluid_mix_balance(prosumer, q_delivered_kw, mdot_out_kg_per_s,
                                          t_out_c, t_return_req_c, result_mdot_tab_kg_per_s,
                                          cp_kj_per_kgk)
            self.finalize(prosumer, result, result_fluid_mix)
            self.applied = True
            self.t_previous_in_c = np.nan
            self.t_previous_return_c = np.nan
            self.mdot_previous_in_kg_per_s = np.nan
        else:
            # Reapply the upstream controllers with the new return temperature
            # so no energy appears or disappears
            self._unapply_initiators(prosumer)
            self.t_previous_in_c = t_in_c
            self.t_previous_return_c = t_return_req_c
            self.mdot_previous_in_kg_per_s = mdot_in_kg_per_s
            self.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: np.nan,
                                              FluidMixMapping.MASS_FLOW_KEY: np.nan}
