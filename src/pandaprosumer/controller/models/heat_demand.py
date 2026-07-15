"""
Module containing the HeatDemandController class.
"""

import numpy as np
import logging

from pandaprosumer.controller.base import BasicProsumerController
from pandaprosumer.mapping.fluid_mix import FluidMixMapping
from pandaprosumer.constants import CELSIUS_TO_K, TEMPERATURE_CONVERGENCE_THRESHOLD_C

logger = logging.getLogger(__name__)


class HeatDemandController(BasicProsumerController):
    """
    Controller for Heat Demand.

    :param prosumer: The prosumer object
    :param heat_demand_object: The heat demand object
    :param order: The order of the controller
    :param level: The level of the controller
    :param in_service: The in-service status of the controller
    :param index: The index of the controller
    :param name: The name of the controller
    :param kwargs: Additional keyword arguments
    """

    def name_class(self):
        return "heat_demand_controller"

    def __init__(self, prosumer, heat_demand_object, order=-1, level=-1,
                 in_service=True, index=None, name=None, **kwargs):
        """
        Initializes the HeatDemandController.
        """
        super().__init__(prosumer, heat_demand_object, order=order, level=level, in_service=in_service,
                         index=index, name=name, **kwargs)
        self.t_previous_out_c = np.nan
        self.t_previous_in_c = np.nan
        self.mdot_previous_in_kg_per_s = np.nan

    @property
    def _q_demand_kw(self):
        return self._get_input('q_demand_kw')

    @property
    def _mdot_demand_kg_per_s(self):
        return self._get_input('mdot_demand_kg_per_s')

    def _t_feed_demand_c(self, prosumer):
        return self._get_input('t_feed_demand_c', prosumer)

    @property
    def _t_return_demand_c(self):
        return self._get_input('t_return_demand_c')

    @property
    def _t_in_c(self):
        if not np.isnan(self.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY]):
            return self.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY]
        else:
            return np.nan
        # return self.inputs[:, self.input_columns.index("fluid_mix")][0][FluidMixMapping.TEMPERATURE_KEY]

    @property
    def _mdot_received_kg_per_s(self):
        if not np.isnan(self.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY]):
            return self.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY]
        else:
            return np.nan
        # if np.isnan(self.inputs[:, self.input_columns.index("fluid_mix")][0]):
        #     return np.nan
        # return self.inputs[:, self.input_columns.index("fluid_mix")][0][FluidMixMapping.MASS_FLOW_KEY]

    def q_to_receive_kw(self, prosumer):
        """
        Calculates the heat to receive in kW.

        :param prosumer: The prosumer object
        :return: Heat to receive in kW
        """
        self.applied = False
        q_to_receive_kw = 0.
        for responder in self._get_generic_mapped_responders(prosumer):
            # The demand is normally not mapped to anything
            q_to_receive_kw += responder.q_to_receive_kw(prosumer)
        q_to_receive_kw += self._q_demand_kw  # The actual demand
        if not np.isnan(self._get_input('q_received_kw')):
            # If there is already some power in the input, don't require it again
            q_received_kw = self._get_input('q_received_kw')
            q_to_receive_kw -= q_received_kw
            q_to_receive_kw = max(0., q_to_receive_kw)
        return q_to_receive_kw

    def _demand_q_tf_tr_m(self, prosumer):
        # Time-series-only reads (no element fallback) to enforce the "3 of 4" rule on
        # explicitly-mapped inputs. Element defaults are silent fallbacks and shouldn't
        # count toward the "all four specified" error.
        t_feed_ts = self._get_input('t_feed_demand_c')
        t_return_ts = self._get_input('t_return_demand_c')
        q_ts = self._q_demand_kw
        mdot_ts = self._mdot_demand_kg_per_s

        if not (np.isnan(t_feed_ts) or np.isnan(t_return_ts) or np.isnan(q_ts) or np.isnan(mdot_ts)):
            raise ValueError("Should not provide a value for all Heat Demand inputs")

        # Effective values (time-series input → element default fallback via _get_input).
        t_feed_demand_c = self._get_input('t_feed_demand_c', prosumer)
        t_return_demand_c = self._get_input('t_return_demand_c', prosumer)
        mdot_demand_kg_per_s = mdot_ts
        effective_q_demand_kw = q_ts

        # Derive any temperature still missing from {t_return, q, mdot} or {t_feed, q, mdot}.
        if np.isnan(t_feed_demand_c) and not (np.isnan(t_return_demand_c) or np.isnan(q_ts) or np.isnan(mdot_ts)):
            cp = float(prosumer.fluid.get_heat_capacity(CELSIUS_TO_K + t_return_demand_c)) / 1000
            t_feed_demand_c = t_return_demand_c + q_ts / (mdot_ts * cp)

        if np.isnan(t_return_demand_c) and not (np.isnan(q_ts) or np.isnan(mdot_ts)):
            if abs(mdot_ts) < 1e-12:
                if not np.isnan(q_ts) and abs(q_ts) > 1e-12:
                    logger.warning(
                        f"Heat Demand {self.name}: Mass flow is zero but heat demand is {q_ts} kW. "
                        f"Effective heat demand will be set to 0 kW since no mass flow means no heat transfer. "
                        f"Timestep: {self.time}"
                    )
                t_return_demand_c = t_feed_demand_c
                effective_q_demand_kw = 0.0
            else:
                cp = float(prosumer.fluid.get_heat_capacity(CELSIUS_TO_K + t_feed_demand_c)) / 1000
                t_return_demand_c = t_feed_demand_c - q_ts / (mdot_ts * cp)
        elif not np.isnan(mdot_ts) and abs(mdot_ts) < 1e-12:
            if not np.isnan(q_ts) and abs(q_ts) > 1e-12:
                logger.warning(
                    f"Heat Demand {self.name}: Mass flow is zero but heat demand is {q_ts} kW. "
                    f"Effective heat demand will be set to 0 kW since no mass flow means no heat transfer. "
                    f"Timestep: {self.time}"
                )
            effective_q_demand_kw = 0.0

        if np.isnan(mdot_demand_kg_per_s):
            if np.isnan(q_ts):
                raise ValueError("Should provide at least mdot_demand_kg_per_s or q_demand_kw as Heat Demand input")
            t_mean_c = (t_feed_demand_c + t_return_demand_c) / 2
            cp = float(prosumer.fluid.get_heat_capacity(CELSIUS_TO_K + t_mean_c)) / 1000
            if abs(t_feed_demand_c - t_return_demand_c) < 1e-12:
                mdot_demand_kg_per_s = 0
            else:
                mdot_demand_kg_per_s = q_ts / (cp * (t_feed_demand_c - t_return_demand_c))

        if np.isnan(q_ts):
            t_mean_c = (t_feed_demand_c + t_return_demand_c) / 2
            cp = float(prosumer.fluid.get_heat_capacity(CELSIUS_TO_K + t_mean_c)) / 1000
            q_demand_kw = mdot_demand_kg_per_s * cp * (t_feed_demand_c - t_return_demand_c)
        else:
            q_demand_kw = effective_q_demand_kw

        return q_demand_kw, t_feed_demand_c, t_return_demand_c, mdot_demand_kg_per_s

    def _t_m_to_receive_init(self, prosumer):
        """
        Return the expected received Feed temperature, return temperature and mass flow in °C and kg/s

        :param prosumer: The prosumer object
        :return: A Tuple (Feed temperature, return temperature and mass flow)
        """
        q_demand_kw, t_feed_demand_c, t_return_demand_c, mdot_demand_kg_per_s = self._demand_q_tf_tr_m(prosumer)
        if not np.isnan(self.t_previous_out_c):
            return self.t_previous_in_c, self.t_previous_out_c, self.mdot_previous_in_kg_per_s
        else:
            if t_feed_demand_c <= t_return_demand_c or mdot_demand_kg_per_s < 1e-12:
                t_feed_demand_c = t_return_demand_c
                mdot_demand_kg_per_s = 0
            if np.isnan(t_feed_demand_c) or np.isnan(t_return_demand_c) or np.isnan(mdot_demand_kg_per_s):
                raise ValueError(
                    f"Heat Demand {self.name}: under-specified demand at timestep {self.time} "
                    f"(t_feed={t_feed_demand_c}, t_return={t_return_demand_c}, mdot={mdot_demand_kg_per_s}). "
                    f"Provide either a time-series input or an element default for each missing field."
                )
            if mdot_demand_kg_per_s < 0:
                raise ValueError(
                    f"Heat Demand {self.name}: negative mass flow ({mdot_demand_kg_per_s} kg/s) "
                    f"at timestep {self.time}"
                )
            if t_feed_demand_c < t_return_demand_c:
                raise ValueError(
                    f"Heat Demand {self.name}: t_feed_demand_c ({t_feed_demand_c}) is colder than "
                    f"t_return_demand_c ({t_return_demand_c}) at timestep {self.time}"
                )
            return t_feed_demand_c, t_return_demand_c, mdot_demand_kg_per_s

    def _save_state(self):
        """Backup states before Run"""
        self._backup_state = {
            "t_previous_out_c": self.t_previous_out_c,
            "t_previous_in_c": self.t_previous_in_c,
            "mdot_previous_in_kg_per_s": self.mdot_previous_in_kg_per_s,
        }

    def _restore_state(self):
        """Restore states before Rerun"""
        if hasattr(self, "_backup_state"):
            self.t_previous_out_c = self._backup_state["t_previous_out_c"]
            self.t_previous_in_c = self._backup_state["t_previous_in_c"]
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

        if not (self.in_service and getattr(prosumer, self.obj.element_name).iloc[self.obj.element_index[0]].in_service):
            self.applied = True
            return

        super().control_step(prosumer)

        if not self._are_initiators_converged(prosumer):
            # If some of the initiators are not converged, do not run the control step
            self._unapply_initiators(prosumer)
            self.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: np.nan,
                                              FluidMixMapping.MASS_FLOW_KEY: np.nan}
            return

        if not np.isnan(self._get_input('q_received_kw')):
            # Case where the Heat Demand is mapped from another controller with a Generic Mapping
            q_received_kw = self._get_input('q_received_kw')
            q_uncovered_kw = self._q_demand_kw - q_received_kw
            result = np.array([[q_received_kw, q_uncovered_kw, 0, 0, 0]])
            self.last_result = {
                "q_received_kw": q_received_kw,
                "q_uncovered_kw": q_uncovered_kw,
                "mdot_received_kg_per_s": 0,
                "t_in_c": 0,
                "t_out_c": 0
            }

            self.finalize(prosumer, result)
            self.applied = True
            return
        
        # Case where the Heat Demand is mapped from another controller with a FluidMix Mapping

        q_demand_kw, t_feed_demand_c, t_return_demand_c, mdot_demand_kg_per_s = self._demand_q_tf_tr_m(prosumer)

        # ToDo: If t_in < t_out, return t_in, not t_out

        if np.isnan(self._t_in_c):
            # Upstream FluidMix initiator (HP, HX, etc.) didn't supply any fluid this
            # step — typically because a source controller was off. Without an inlet temperature
            # the heat demand can't compute mass flow. Treat the entire demand as
            # uncovered for this step instead of crashing the whole timeseries.
            result = np.array([[0.0, q_demand_kw, 0.0, 0.0, t_return_demand_c]])
            self.last_result = {
                "q_received_kw": 0.0,
                "q_uncovered_kw": q_demand_kw,
                "mdot_received_kg_per_s": 0.0,
                "t_in_c": 0.0,
                "t_out_c": t_return_demand_c,
            }
            self.finalize(prosumer, result)
            self.applied = True
            self.t_previous_out_c = np.nan
            self.t_previous_in_c = np.nan
            self.mdot_previous_in_kg_per_s = np.nan
            return

        assert not np.isnan(self._t_in_c), f"Heat Demand {self.name} t_in_c is NaN for timestep {self.time} in prosumer {prosumer.name}"
        assert not np.isnan(t_feed_demand_c), f"Heat Demand {self.name} t_feed_demand_c is NaN for timestep {self.time} in prosumer {prosumer.name}"
        assert not np.isnan(t_return_demand_c), f"Heat Demand {self.name} t_return_demand_c is NaN for timestep {self.time} in prosumer {prosumer.name}"
        assert not np.isnan(q_demand_kw), f"Heat Demand {self.name} q_demand_kw is NaN for timestep {self.time} in prosumer {prosumer.name}"
        assert not np.isnan(mdot_demand_kg_per_s), f"Heat Demand {self.name} mdot_demand_kg_per_s is NaN for timestep {self.time} in prosumer {prosumer.name}"

        t_mean_c = (self._t_in_c + t_return_demand_c) / 2
        cp_kj_per_kgk = float(prosumer.fluid.get_heat_capacity(CELSIUS_TO_K + t_mean_c)) / 1000
        if np.isnan(self._mdot_received_kg_per_s):
            q_received_kw = q_demand_kw
            # Handle division by zero when temperatures are equal
            if abs(self._t_in_c - t_return_demand_c) < 1e-12:
                # When temperatures are equal, mass flow can be anything (we use 0)
                mdot_received_kg_per_s = 0
            else:
                mdot_received_kg_per_s = q_demand_kw / (cp_kj_per_kgk * (self._t_in_c - t_return_demand_c))
        else:
            mdot_received_kg_per_s = self._mdot_received_kg_per_s
            q_received_kw = cp_kj_per_kgk * mdot_received_kg_per_s * (self._t_in_c - t_return_demand_c)
        t_out_c = t_return_demand_c
        # Calculate the difference between the received and the required power, wo considering the temperature level
        # FixMe: Consider the temperature level in the output
        q_uncovered_kw = q_demand_kw - q_received_kw
        result = np.array([[q_received_kw, q_uncovered_kw, mdot_received_kg_per_s, self._t_in_c, t_out_c]])
        self.last_result = {
            "q_received_kw": q_received_kw,
            "q_uncovered_kw": q_uncovered_kw,
            "mdot_received_kg_per_s": mdot_received_kg_per_s,
            "t_in_c": self._t_in_c,
            "t_out_c": t_out_c
        }
        if np.isnan(result).any():
            self.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: np.nan,
                                              FluidMixMapping.MASS_FLOW_KEY: np.nan}
        else:
            if np.isnan(self.t_keep_return_c) or mdot_received_kg_per_s == 0 or abs(t_out_c - self.t_keep_return_c) < TEMPERATURE_CONVERGENCE_THRESHOLD_C:  # or len(self._get_mapped_initiators_on_same_level(prosumer)) == 0:
                # If the actual output temperature is the same as the promised one, the storage is correctly applied
                self.finalize(prosumer, result)
                self.applied = True
                self.t_previous_out_c = np.nan
                self.t_previous_in_c = np.nan
                self.mdot_previous_in_kg_per_s = np.nan
            else:
                # Else, reapply the upstream controllers with the new temperature so no energy appears or disappears
                self._unapply_initiators(prosumer)
                self.t_previous_out_c = t_out_c
                self.t_previous_in_c = self._t_in_c
                self.mdot_previous_in_kg_per_s = mdot_received_kg_per_s
                self.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: np.nan,
                                                  FluidMixMapping.MASS_FLOW_KEY: np.nan}
