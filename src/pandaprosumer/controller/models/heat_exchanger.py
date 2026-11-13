"""
Module containing the HeatExchangerController class.
"""

import logging
import numpy as np
from pandapipes import call_lib

from pandaprosumer.controller.base import BasicProsumerController
from pandaprosumer.controller.return_temperature import ReturnTemperatureSolver
from pandaprosumer.constants import CELSIUS_TO_K, TEMPERATURE_CONVERGENCE_THRESHOLD_C, MAX_RERUN
from pandaprosumer.mapping import FluidMixMapping
from pandaprosumer.library.heat_exchanger_utils import compute_temp

#: Lowest secondary return the exchanger guesses when its feed is too cold for the requested outlet [°C]
WATER_FREEZING_POINT_C = 0.

logger = logging.getLogger(__name__)


class HeatExchangerController(BasicProsumerController):
    """
    Controller for Heat Exchanger systems.

    The heat exchanger is implemented from KS conservation and logarithmic mean temperature difference (LMTD)

    In the heat exchanger element some nominal temperatures and mass flows are specified.
    The resulting return temperature on the primary side is calculated from this state,
    then the primary mass flow is deducted.

    The temperature on the primary side must be higher than on the secondary (t_in_1 > t_out_2 and t_out_1 > t_in_2).

    Primary:
    t_in_1 = t_hot_1 = t_feed_1
    t_out_1 = t_cold_1 = t_return_1 (result of _compute_temp)

    Secondary:
    t_in_2 = t_cold_2 = t_return_2
    t_out_2 = t_hot_2 = t_feed_2

    :param prosumer: The prosumer object
    :param heat_exchanger_object: The heat exchanger object
    :param order: The order of the controller
    :param level: The level of the controller
    :param in_service: The in-service status of the controller
    :param index: The index of the controller
    :param kwargs: Additional keyword arguments
    """

    def name_class(self):
        return "heat_exchanger_controller"

    def __init__(self, prosumer, heat_exchanger_object, order, level,
                 in_service=True, index=None, name=None, **kwargs):
        """
        Constructor method
        """
        super().__init__(prosumer, heat_exchanger_object, order=order, level=level, in_service=in_service,
                         index=index, name=name, **kwargs)
        primary_fluid = self._get_element_param(prosumer, 'primary_fluid')
        secondary_fluid = self._get_element_param(prosumer, 'secondary_fluid')
        if primary_fluid and primary_fluid != prosumer.fluid.name:
            self.primary_fluid = call_lib(primary_fluid)
        else:
            self.primary_fluid = prosumer.fluid
        if secondary_fluid and secondary_fluid != prosumer.fluid.name:
            self.secondary_fluid = call_lib(secondary_fluid)
        else:
            self.secondary_fluid = prosumer.fluid

        self.t_previous_1_out_c = np.nan
        self.t_previous_1_in_c = np.nan
        self.mdot_previous_1_kg_per_s = np.nan

    # FixMe: Fix the mapping (generic or fluid mix) and how to handle _mdot_feedin_kg_per_s
    @property
    def _t_feed_in_c(self):
        if not np.isnan(self.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY]):
            return self.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY]
        else:
            return self.inputs[:, self.input_columns.index("t_feed_in_c")][0]

    @property
    def _mdot_1_provided_kg_per_s(self):
        if not np.isnan(self.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY]):
            return self.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY]
        else:
            return np.nan

    def _t_m_to_receive_init(self, prosumer):
        """
        Return the expected received Feed temperature, return temperature and mass flow in °C and kg/s

        :param prosumer: The prosumer object
        :return: A Tuple (Feed temperature, return temperature and mass flow)
        """
        t_feed_demand_c, t_return_demand_c, mdot_demand_kg_per_s = self.t_m_to_deliver(prosumer)
        if not np.isnan(self.t_previous_1_out_c):
            return self.t_previous_1_in_c, self.t_previous_1_out_c, self.mdot_previous_1_kg_per_s
        else:
            delta_t_hot_default_c = self._get_element_param(prosumer, 'delta_t_hot_default_c')
            return self.t_m_to_receive_for_t(prosumer, t_feed_demand_c + delta_t_hot_default_c)

    def t_m_to_receive_for_t(self, prosumer, t_feed_c):
        """
        For a given feed temperature in °C, calculate the required feed mass flow and the expected return temperature 
        if this feed temperature is provided.

        :param prosumer: The prosumer object
        :param t_feed_c: The feed temperature
        :return: A Tuple (Feed temperature, return temperature and mass flow)
        """
        t_out_2_required_c, t_in_2_required_c, mdot_tab_required_kg_per_s = self.t_m_to_deliver(prosumer)
        mdot_2_required_kg_per_s = sum(mdot_tab_required_kg_per_s)

        t_1_in_c = t_feed_c

        if mdot_2_required_kg_per_s < 1e-6 or abs(t_out_2_required_c - t_in_2_required_c) < 1e-3:
            # If the secondary mass flow is too low, no heat is exchanged
            t_1_out_c = t_1_in_c
            mdot_1_kg_per_s = 0
        else:
            (mdot_1_kg_per_s, t_1_in_c, t_1_out_c,
             mdot_2_kg_per_s, t_2_in_c, t_2_out_c) = self.calculate_heat_exchanger(prosumer,
                                                                                   t_out_2_required_c,
                                                                                   t_in_2_required_c,
                                                                                   mdot_2_required_kg_per_s,
                                                                                   t_1_in_c)

        if not np.isnan(self.t_previous_1_out_c):
            mdot_previous_1_in_kg_per_s = self.mdot_previous_1_kg_per_s
            if mdot_previous_1_in_kg_per_s < 0:
                raise ValueError(
                    f"Heat Exchanger {self.name}: previous-step primary mass flow is negative "
                    f"({mdot_previous_1_in_kg_per_s} kg/s)"
                )
            if self.t_previous_1_in_c < self.t_previous_1_out_c:
                raise ValueError(
                    f"Heat Exchanger {self.name}: previous-step t_1_in_c ({self.t_previous_1_in_c}) "
                    f"is colder than t_1_out_c ({self.t_previous_1_out_c})"
                )
            return self.t_previous_1_in_c, self.t_previous_1_out_c, mdot_previous_1_in_kg_per_s

        if np.isnan(t_1_in_c) or np.isnan(t_1_out_c) or np.isnan(mdot_1_kg_per_s):
            raise ValueError(
                f"Heat Exchanger {self.name}: primary-side computation produced nan at timestep "
                f"{self.time} (t_1_in={t_1_in_c}, t_1_out={t_1_out_c}, mdot_1={mdot_1_kg_per_s})"
            )
        if mdot_1_kg_per_s < 0:
            raise ValueError(
                f"Heat Exchanger {self.name}: Negative mass flow {mdot_1_kg_per_s} kg/s at "
                f"timestep {self.time} in prosumer {prosumer.name}"
            )
        if t_1_in_c < t_1_out_c:
            raise ValueError(
                f"Heat Exchanger {self.name}: t_1_in_c ({t_1_in_c}) is colder than t_1_out_c "
                f"({t_1_out_c}) at timestep {self.time}"
            )
        return t_1_in_c, t_1_out_c, mdot_1_kg_per_s

    def _starved_primary_flow_kg_per_s(self, prosumer, mdot_2_kg_per_s, t_2_out_c, t_2_in_c):
        """
        The primary flow the exchanger draws when its feed is too cold to heat with: the flow its secondary demand
        would need at the nominal primary temperatures.
        """
        delta_t_1_nom_c = (self._get_element_param(prosumer, 't_1_in_nom_c')
                           - self._get_element_param(prosumer, 't_1_out_nom_c'))
        if delta_t_1_nom_c <= 0 or t_2_out_c <= t_2_in_c:
            return 0.
        cp_2_j_per_kgk = self.secondary_fluid.get_heat_capacity(CELSIUS_TO_K + (t_2_out_c + t_2_in_c) / 2)
        cp_1_j_per_kgk = self.primary_fluid.get_heat_capacity(CELSIUS_TO_K + self._get_element_param(prosumer, 't_1_in_nom_c'))
        q_asked_w = mdot_2_kg_per_s * cp_2_j_per_kgk * (t_2_out_c - t_2_in_c)
        return q_asked_w / (cp_1_j_per_kgk * delta_t_1_nom_c)

    def _primary_mdot_kg_per_s(self, q_exchanged_w, t_1_in_c, t_1_out_c, mdot_1_kg_per_s):
        """
        Primary mass flow carrying ``q_exchanged_w`` from ``t_1_in_c`` to ``t_1_out_c``, with the heat capacity
        at the primary mean temperature: the one ``q_exchanged_kw`` is booked with. :func:`compute_temp` sizes
        it with the capacity at the primary inlet (it does not know the outlet yet), 0.5 % higher for water
        at 95 °C than at the 70 °C mean: the exchanger then booked 0.45 % less heat than its demands received.
        Left as is when the primary does not cool (no exchange).
        """
        if t_1_in_c - t_1_out_c <= 0 or mdot_1_kg_per_s <= 0:
            return mdot_1_kg_per_s
        cp_1_j_per_kgk = self.primary_fluid.get_heat_capacity(CELSIUS_TO_K + (t_1_in_c + t_1_out_c) / 2)
        return q_exchanged_w / (cp_1_j_per_kgk * (t_1_in_c - t_1_out_c))

    def calculate_heat_exchanger(self, prosumer, t_2_out_c, t_2_in_c, mdot_2_kg_per_s, t_1_in_c):
        """
        Main Heat Exchanger calculation method

        :param prosumer: The prosumer object
        :param t_2_out_c: The secondary output (hot feed pipe) temperature
        :param t_2_in_c: The secondary input (cold return pipe) temperature
        :param mdot_2_kg_per_s: The secondary mass flow
        :param t_1_in_c: The primary input (hot feed pipe) temperature
        """
        t_1_hot_nom_c = self._get_element_param(prosumer, 't_1_in_nom_c')
        t_1_cold_nom_c = self._get_element_param(prosumer, 't_1_out_nom_c')
        t_2_cold_nom_c = self._get_element_param(prosumer, 't_2_in_nom_c')
        t_2_hot_nom_c = self._get_element_param(prosumer, 't_2_out_nom_c')
        mdot_2_nom_kg_per_s = self._get_element_param(prosumer, 'mdot_2_nom_kg_per_s')

        delta_t_2_c = t_2_out_c - t_2_in_c

        cp_2_j_per_kgk = self.secondary_fluid.get_heat_capacity(CELSIUS_TO_K + (t_2_out_c + t_2_in_c) / 2)
        cp_1_j_per_kgk = self.primary_fluid.get_heat_capacity(CELSIUS_TO_K + t_1_in_c)
        q_exchanged_w = cp_2_j_per_kgk * mdot_2_kg_per_s * delta_t_2_c

        max_q_kw = self._get_element_param(prosumer, 'max_q_kw')
        if q_exchanged_w > max_q_kw * 1000:
            q_exchanged_w = max_q_kw * 1000
            mdot_2_kg_per_s = max_q_kw * 1000 / (cp_2_j_per_kgk * delta_t_2_c)

        delta_t_2_nom_c = t_2_hot_nom_c - t_2_cold_nom_c
        cp_2_nom_j_per_kg_k = self.secondary_fluid.get_heat_capacity(CELSIUS_TO_K + (t_2_hot_nom_c + t_2_cold_nom_c) / 2)
        q_exchanged_nom_w = cp_2_nom_j_per_kg_k * mdot_2_nom_kg_per_s * delta_t_2_nom_c
        q_ratio = q_exchanged_w / q_exchanged_nom_w

        delta_t_hot_nom_c = t_1_hot_nom_c - t_2_hot_nom_c
        delta_t_cold_nom_c = t_1_cold_nom_c - t_2_cold_nom_c
        delta_t_hot_c = t_1_in_c - t_2_out_c
        
        if delta_t_hot_c <= 0:
            # No hot approach: the primary cannot heat the secondary to the outlet asked, no exchange on either
            # side (:meth:`control_step` lowers the outlet first; :meth:`t_m_to_receive_for_t` asks as is)
            return 0., t_1_in_c, t_1_in_c, 0., t_2_in_c, t_2_in_c
        
        # Logarithmic mean temperature difference (LMTD) at nominal conditions
        if delta_t_hot_nom_c == delta_t_cold_nom_c:
            lmtd_nom = delta_t_hot_nom_c
        else:
            lmtd_nom = (delta_t_hot_nom_c - delta_t_cold_nom_c) / np.log(delta_t_hot_nom_c / delta_t_cold_nom_c)
        a = delta_t_hot_c / (q_ratio * lmtd_nom)

        min_delta_t_1_c = self._get_element_param(prosumer, 'min_delta_t_1_c')
        max_t_1_out_c = t_1_in_c - min_delta_t_1_c
        min_x = 1 - (max_t_1_out_c - t_2_in_c) / delta_t_hot_c

        if min_x >= 1 :
            # If t_2_in_c >= max_t_1_out, ignore min_delta_t_1_c but calculate which q_exchanged will give
            # a higher t_1_out_c
            # ToDo: create test for this case
            min_delta_t_cold_c = 3  # ToDo: constant
            # Stall the HX when the secondary cold-side is so warm that even a
            # minimal `min_delta_t_cold_c` approach drives t_1_out_c above t_1_in_c.
            # Physically the exchanger cannot cool the primary in this regime — pretend
            # there is no flow, no exchange.
            # Stall when the cold-approach floor pushes t_1_out_c above t_1_in_c, OR
            # when the hot-side approach (delta_t_hot_c) is smaller than the cold-
            # approach floor — both regimes are physically infeasible (the HX cannot
            # transfer the required heat with these temperature constraints) and the
            # downstream LMTD math degenerates (x outside (0, 1)).
            if t_2_in_c + min_delta_t_cold_c > t_1_in_c or delta_t_hot_c <= min_delta_t_cold_c:
                return 0.0, t_1_in_c, t_1_in_c, 0.0, t_2_in_c, t_2_in_c
            t_1_out_c = t_2_in_c + min_delta_t_cold_c
            x = 1 - min_delta_t_cold_c / delta_t_hot_c
            if x > 0 and x < 1:
                a = -np.log(1 - x) / x
            else:
                # Same physically infeasible regime, caught by the math instead of the
                # geometric check above (e.g. floating-point edges). Stall rather than
                # propagate a ValueError that kills the whole timeseries.
                return 0.0, t_1_in_c, t_1_in_c, 0.0, t_2_in_c, t_2_in_c
            q_exchanged_w = (delta_t_hot_c * q_exchanged_nom_w) / (a * lmtd_nom)
            mdot_2_kg_per_s = q_exchanged_w / (cp_2_j_per_kgk * delta_t_2_c)
            t_mean_1_c = CELSIUS_TO_K + (t_1_in_c + t_1_out_c) / 2
            cp_1_j_per_kgk = self.primary_fluid.get_heat_capacity(t_mean_1_c)
            mdot_1_kg_per_s = q_exchanged_w / (cp_1_j_per_kgk * (t_1_in_c - t_1_out_c))

        else:
            min_a = -np.log(1 - min_x) / min_x if min_x != 0 else 1

            if a < min_a:
                # If 'a' is too low, q_exchanged_w is too big so reduce mdot_2_kg_per_s
                # else t_1_out_c would be hotter than t_1_in_c
                a = min_a
                q_ratio = delta_t_hot_c / (min_a * lmtd_nom)
                q_exchanged_w = q_ratio * q_exchanged_nom_w
                mdot_2_kg_per_s = q_exchanged_w / (cp_2_j_per_kgk * delta_t_2_c)
                # delta_t_cold = _calculate_cold_temperature_difference(a, delta_t_hot_c)
                t_1_out_c = max_t_1_out_c
                t_mean_1_c = CELSIUS_TO_K + (t_1_in_c + t_1_out_c) / 2
                mdot_1_kg_per_s = q_exchanged_w / (self.primary_fluid.get_heat_capacity(t_mean_1_c) * (t_1_in_c - t_1_out_c))
            else:
                t_1_out_c, mdot_1_kg_per_s = compute_temp(q_ratio, q_exchanged_w, t_1_in_c, t_2_in_c, t_2_out_c,
                                                          delta_t_hot_nom_c, delta_t_cold_nom_c, cp_1_j_per_kgk,
                                                          heat_consumer=False)
                mdot_1_kg_per_s = self._primary_mdot_kg_per_s(q_exchanged_w, t_1_in_c, t_1_out_c, mdot_1_kg_per_s)

        # Energy conservation at the exchanger boundary: if the primary side ended up with no
        # flow, no heat can reach the secondary side either. Without this the responder (heat
        # demand / storage) booked mdot_2 * cp * (t_2_out - t_2_in) while the exchanger booked 0.
        if mdot_1_kg_per_s < 1e-6:
            mdot_2_kg_per_s = 0.
            t_2_out_c = t_2_in_c
        return mdot_1_kg_per_s, t_1_in_c, t_1_out_c, mdot_2_kg_per_s, t_2_in_c, t_2_out_c

    def calculate_heat_exchanger_reverse(self, prosumer, t_2_out_c, t_2_in_c, mdot_2_kg_per_s, t_1_in_c,
                                         mdot_1_kg_per_s):
        """
        Heat Exchanger calculation when the primary flow is short: the inverse of :meth:`calculate_heat_exchanger`.

        The secondary keeps the outlet temperature it asked for and gets the flow the primary it is fed can
        heat to it: the secondary flow for which the forward calculation draws exactly ``mdot_1_kg_per_s``
        on the primary, found by dichotomy (the primary flow grows with the secondary one). Continuous with
        the forward calculation at the flow it asked: a primary barely short gives a secondary barely short.
        The former reverse kept the primary outlet of the forward solution and solved the LMTD for the
        secondary outlet with the heat the primary flow carries to it: not the inverse of the forward
        calculation (a primary 0.03 % short gave a secondary outlet 2 K colder carrying 9 % more flow; with
        the primary outlet pinned by ``min_delta_t_1_c``, a primary half short gave an outlet 19 K hotter
        than asked).

        :param prosumer: The prosumer object
        :param t_2_out_c: The secondary output (hot feed pipe) temperature in °C
        :param t_2_in_c: The secondary input (cold return pipe) temperature in °C
        :param mdot_2_kg_per_s: The secondary mass flow asked in kg/s, an upper bound of the one delivered
        :param t_1_in_c: The primary input (hot feed pipe) temperature in °C
        :param mdot_1_kg_per_s: The primary mass flow provided in kg/s, less than the forward calculation draws
        :return: The same tuple as :meth:`calculate_heat_exchanger`, with the primary mass flow provided
        """
        if mdot_1_kg_per_s < 1e-6:
            return 0., t_1_in_c, t_1_in_c, 0., t_2_in_c, t_2_in_c

        def forward(mdot_2_asked_kg_per_s):
            return self.calculate_heat_exchanger(prosumer, t_2_out_c, t_2_in_c, mdot_2_asked_kg_per_s, t_1_in_c)

        # The primary flow is 0 for no secondary flow and above the one provided for the secondary flow asked
        # (the caller's condition): bisect the secondary flow between the two
        mdot_2_low_kg_per_s, mdot_2_high_kg_per_s = 0., mdot_2_kg_per_s
        for _ in range(100):
            mdot_2_mid_kg_per_s = (mdot_2_low_kg_per_s + mdot_2_high_kg_per_s) / 2
            result = forward(mdot_2_mid_kg_per_s)
            if abs(result[0] - mdot_1_kg_per_s) <= 1e-9 * mdot_1_kg_per_s:
                break
            if result[0] < mdot_1_kg_per_s:
                mdot_2_low_kg_per_s = mdot_2_mid_kg_per_s
            else:
                mdot_2_high_kg_per_s = mdot_2_mid_kg_per_s
            if mdot_2_high_kg_per_s - mdot_2_low_kg_per_s <= 1e-12 * mdot_2_kg_per_s:
                break
        _, t_1_in_c, t_1_out_c, mdot_2_kg_per_s, t_2_in_c, t_2_out_c = result
        if mdot_2_kg_per_s < 1e-6:
            # The primary flow is too low to heat any secondary flow: no heat is exchanged
            return 0., t_1_in_c, t_1_in_c, 0., t_2_in_c, t_2_in_c
        return mdot_1_kg_per_s, t_1_in_c, t_1_out_c, mdot_2_kg_per_s, t_2_in_c, t_2_out_c

    def _save_state(self):
        """Backup states before Run"""
        self._backup_state = {
            "t_previous_1_out_c": self.t_previous_1_out_c,
            "t_previous_1_in_c": self.t_previous_1_in_c,
            "mdot_previous_1_kg_per_s": self.mdot_previous_1_kg_per_s,
        }

    def _restore_state(self):
        """Restore states before Rerun"""
        if hasattr(self, "_backup_state"):
            self.t_previous_1_out_c = self._backup_state["t_previous_1_out_c"]
            self.t_previous_1_in_c = self._backup_state["t_previous_1_in_c"]
            self.mdot_previous_1_kg_per_s = self._backup_state["mdot_previous_1_kg_per_s"]

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
            self.obj.element_index[0]].in_service):  # FixMe: use gettattr element
            self.applied = True
            return

        super().control_step(prosumer)

        if not self._are_initiators_converged(prosumer):
            # If some of the initiators are not converged, do not run the control step
            self._unapply_initiators(prosumer)
            self.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: np.nan,
                                              FluidMixMapping.MASS_FLOW_KEY: np.nan}
            return

        t_out_2_required_c, t_in_2_required_c, mdot_tab_required_kg_per_s = self.t_m_to_deliver(prosumer)
        mdot_2_required_kg_per_s = sum(mdot_tab_required_kg_per_s)
        if getattr(self, "_first_ask_time", None) != self.time:
            # What the secondary asks on the step's first pass: on the next passes a demand fed too cold answers
            # with its pass-through (no flow, return = feed), and the starved exchanger must still know what it was
            # asked.
            self._first_ask_time = self.time
            self._first_ask = (t_out_2_required_c, t_in_2_required_c, mdot_2_required_kg_per_s)

        t_1_in_c = self._t_feed_in_c
        

        assert not np.isnan(t_1_in_c), f"Heat Exchanger {self.name} t_1_in_c is NaN for timestep {self.time} in prosumer {prosumer.name}"
        assert not np.isnan(t_out_2_required_c), f"Heat Exchanger {self.name} t_out_2_required_c is NaN for timestep {self.time} in prosumer {prosumer.name}"
        assert not np.isnan(t_in_2_required_c), f"Heat Exchanger {self.name} t_in_2_required_c is NaN for timestep {self.time} in prosumer {prosumer.name}"
        assert not np.isnan(mdot_2_required_kg_per_s), f"Heat Exchanger {self.name} mdot_2_required_kg_per_s is NaN for timestep {self.time} in prosumer {prosumer.name}"

        t_in_2_promised_c = t_in_2_required_c
        too_cold_to_heat = False
        min_approach_c = min(self._get_element_param(prosumer, 'delta_t_hot_default_c'), 5)
        if t_1_in_c < t_out_2_required_c + min_approach_c:
            # A feed too close to (or colder than) the requested outlet: the outlet slides down with the feed,
            # keeping a hot-end approach of `min_approach_c`. Sliding only below the outlet left a feed a fraction
            # of a degree above it with no approach at all: the LMTD then wants a barely cooled primary, i.e. a
            # primary flow ten times its nominal one (game sandbox: 9.7 kg/s at 70.2 degC for a 70 degC outlet),
            # which drained the network's heat in one hour and starved every substation the next.
            # Once the outlet reaches the return, the return is only a guess keeping the secondary temperature
            # difference -- a responder whose return is an outcome (a dry cooler) answers with the real one and
            # reruns this exchanger -- bounded by the freezing point of water: unbounded, a cooled network drove
            # it to -24 degC. An outlet landing on the return, or a feed too cold to heat water above the freezing
            # point, exchanges nothing.
            t_out_2_lowered_c = t_1_in_c - min_approach_c
            if t_out_2_lowered_c < t_in_2_required_c:
                t_in_2_required_c = max(t_in_2_required_c + t_out_2_lowered_c - t_out_2_required_c,
                                        WATER_FREEZING_POINT_C)
            t_out_2_required_c = t_out_2_lowered_c
            too_cold_to_heat = t_out_2_required_c - t_in_2_required_c < 1e-3

        if mdot_2_required_kg_per_s < 1e-6 or abs(t_out_2_required_c - t_in_2_required_c) < 1e-3 or too_cold_to_heat:
            # If the secondary mass flow is too low, no heat is exchanged.
            # The secondary must then leave at its INLET temperature, not at the
            # requested outlet: with the primary idle (mdot_1 = 0, q_exchanged = 0)
            # a warm secondary would let the downstream demand book heat this
            # exchanger never delivered (Paris CPCU<->BET boundary, 0.0006 K at
            # 18.78 kg/s -> 0.049 kW created on the first step of an ON ramp).
            t_1_out_c = t_1_in_c
            mdot_1_kg_per_s = 0
            t_out_2_asked_c, t_in_2_asked_c, mdot_2_asked_kg_per_s = getattr(
                self, "_first_ask", (t_out_2_required_c, t_in_2_promised_c, mdot_2_required_kg_per_s))
            if mdot_2_asked_kg_per_s >= 1e-6 and t_1_in_c < t_out_2_asked_c:
                # Starved by a feed too cold to heat with: a substation's valve opens instead of closing, so
                # the network still circulates (through the exchanger, unheated) and the plant sees the load.
                # Closed, a cooled network drew no flow, a heat-led plant (a CHP) saw no demand and the network
                # never warmed up again (game sandbox: a CHP off overnight stayed off all day).
                mdot_1_kg_per_s = self._starved_primary_flow_kg_per_s(
                    prosumer, mdot_2_asked_kg_per_s, t_out_2_asked_c, t_in_2_asked_c)
            mdot_2_kg_per_s = mdot_2_required_kg_per_s
            t_2_in_c = t_in_2_promised_c
            t_2_out_c = t_in_2_promised_c
            result_mdot_tab_kg_per_s = self._merit_order_mass_flow(prosumer, mdot_2_kg_per_s,
                                                                   mdot_tab_required_kg_per_s)


            # Handle case where primary mass flow is provided but no heat exchange occurs (full bypass)
            if not np.isnan(self._mdot_1_provided_kg_per_s):
                mdot_1_kg_per_s = self._mdot_1_provided_kg_per_s
                # Temperature remains the same (bypass)
                t_1_out_c = t_1_in_c

        else:
            assert t_1_in_c >= t_out_2_required_c, f"Heat Exchanger {self.name} t_1_in_c < t_out_2_required_c ({t_1_in_c} < {t_out_2_required_c}) for timestep {self.time} in prosumer {prosumer.name}"
            assert t_out_2_required_c >= t_in_2_required_c, f"Heat Exchanger {self.name} t_out_2_required_c < t_in_2_required_c ({t_out_2_required_c} < {t_in_2_required_c}) for timestep {self.time} in prosumer {prosumer.name}"

            return_solver = ReturnTemperatureSolver()
            rerun = True
            nb_runs = 0
            while rerun:
                nb_runs += 1
                if nb_runs > MAX_RERUN:
                    raise RuntimeError(
                        f"Heat Exchanger {self.name}: calculation did not converge after "
                        f"{MAX_RERUN} iterations at timestep {self.time} in prosumer {prosumer.name}"
                    )
                (mdot_1_kg_per_s, t_1_in_c, t_1_out_c,
                 mdot_2_kg_per_s, t_2_in_c, t_2_out_c) = self.calculate_heat_exchanger(prosumer,
                                                                                       t_out_2_required_c,
                                                                                       t_in_2_required_c,
                                                                                       mdot_2_required_kg_per_s,
                                                                                       t_1_in_c)

                if not np.isnan(self._mdot_1_provided_kg_per_s):
                    assert self._mdot_1_provided_kg_per_s >= 0, f"Heat Exchanger {self.name} received mass flow is negative for for timestep {self.time} in prosumer {prosumer.name}"
                    # If the primary is fed with a fixed mass flow (not free air)
                    if mdot_1_kg_per_s > self._mdot_1_provided_kg_per_s:
                        # If the primary mass flow is higher than the one provided to the Heat Exchanger,
                        # recalculate the secondary mass flow the provided primary flow can heat to the
                        # requested outlet temperature (the inverse of the calculation above)
                        (mdot_1_kg_per_s, t_1_in_c, t_1_out_c,
                         mdot_2_kg_per_s, t_2_in_c, t_2_out_c) = self.calculate_heat_exchanger_reverse(prosumer,
                                                                                                       t_out_2_required_c,
                                                                                                       t_in_2_required_c,
                                                                                                       mdot_2_required_kg_per_s,
                                                                                                       t_1_in_c,
                                                                                                       self._mdot_1_provided_kg_per_s)
                        assert abs(mdot_1_kg_per_s - self._mdot_1_provided_kg_per_s) < .01,\
                            (f"Heat Exchanger {self.name} mdot_1_kg_per_s != self._mdot_1_provided_kg_per_s"
                             f" ({mdot_1_kg_per_s} != {self._mdot_1_provided_kg_per_s}) for for timestep"
                             f" {self.time} in prosumer {prosumer.name}")

                    elif mdot_1_kg_per_s < self._mdot_1_provided_kg_per_s:
                        # If the primary mass flow is lower than the one required by the Heat Exchanger,
                        # model a bypass on the primary side where the extra mass flow doesn't exchange heat.
                        # Recalculate the primary output temperature
                        mdot_bypass_kg_per_s = self._mdot_1_provided_kg_per_s - mdot_1_kg_per_s
                        t_bypass_c = t_1_in_c
                        t_1_out_c = (t_bypass_c * mdot_bypass_kg_per_s + t_1_out_c * mdot_1_kg_per_s) / self._mdot_1_provided_kg_per_s
                        mdot_1_kg_per_s = self._mdot_1_provided_kg_per_s

                # The secondary flow (what the primary provided can heat, or the forward calculation's cap) is
                # distributed in merit order; the surplus of a storage or a responder asking nothing goes to the
                # others in proportion to their asks
                result_mdot_tab_kg_per_s = self._merit_order_mass_flow(prosumer,
                                                                       mdot_2_kg_per_s,
                                                                       mdot_tab_required_kg_per_s,
                                                                       overflow_strategy="dump_proportional")

                rerun = False
                if (len(self._get_mapped_responders(prosumer)) > 1
                        and (abs(mdot_2_kg_per_s - mdot_2_required_kg_per_s) > 1e-9 or return_solver.started)):
                    # If the heat exchanger does not deliver the required mass flow (short of it, or dumping a
                    # surplus), its secondary return is the mix of what its responders give back for the flows
                    # it delivers, each one returning the same temperature whatever flow it gets: rerun until
                    # the return it is calculated with is that mix
                    t_2_in_mixed_c, t_returns_c = self._mixed_return_temperature_c(prosumer, result_mdot_tab_kg_per_s,
                                                                                   t_in_2_required_c)
                    t_2_in_next_c = return_solver.next_guess(t_in_2_required_c, t_2_in_mixed_c, t_returns_c)
                    if t_2_in_next_c is not None:
                        t_in_2_required_c = t_2_in_next_c
                        rerun = True

            assert abs(mdot_2_kg_per_s - np.sum(result_mdot_tab_kg_per_s)) < 1e-3, \
                (f"Heat Exchanger {self.name} mdot_2_kg_per_s != sum(result_mdot_tab_kg_per_s) "
                 f"({mdot_2_kg_per_s} != {np.sum(result_mdot_tab_kg_per_s)}) for"
                 f" timestep {self.time} in prosumer {prosumer.name}")

        # Snap to t_1_in_c when t_1_out_c overshoots it by float-rounding noise.
        # The LMTD math involves divisions/log so the last ULP of t_1_out_c can sit a
        # few 1e-15 above t_1_in_c when the operating point is right at the limit of
        # the achievable approach (e.g. coupled-sim transients where the secondary
        # cold-side has just barely cooled below t_1_in_c). Without this snap the
        # strict `t_1_out_c <= t_1_in_c` assertion below trips on pure rounding.
        if t_1_out_c > t_1_in_c and (t_1_out_c - t_1_in_c) < 1e-9:
            t_1_out_c = t_1_in_c

        cp_1_kj_per_kg_k = self.primary_fluid.get_heat_capacity(CELSIUS_TO_K + (t_1_in_c + t_1_out_c) / 2) / 1000
        q_exchanged_kw = mdot_1_kg_per_s * cp_1_kj_per_kg_k * (t_1_in_c - t_1_out_c)

        result = np.array(
            [[q_exchanged_kw, mdot_1_kg_per_s, t_1_in_c, t_1_out_c, mdot_2_kg_per_s, t_2_in_c, t_2_out_c]]
        )

        self.last_result = {
            "q_exchanged_kw": q_exchanged_kw,
            "mdot_1_kg_per_s": mdot_1_kg_per_s,
            "t_1_in_c": t_1_in_c,
            "t_1_out_c": t_1_out_c,
            "mdot_2_kg_per_s": mdot_2_kg_per_s,
            "t_2_in_c": t_2_in_c,
            "t_2_out_c": t_2_out_c,
        }

        result_fluid_mix = []
        for mdot_kg_per_s in result_mdot_tab_kg_per_s:
            result_fluid_mix.append({FluidMixMapping.TEMPERATURE_KEY: t_2_out_c,
                                     FluidMixMapping.MASS_FLOW_KEY: mdot_kg_per_s})

        assert t_2_out_c >= 0, f"Heat Exchanger {self.name} t_2_out_c is negative ({t_2_out_c}) for timestep {self.time} in prosumer {prosumer.name}"
        assert t_2_in_c >= 0, f"Heat Exchanger {self.name} t_2_in_c is negative ({t_2_in_c}) for timestep {self.time} in prosumer {prosumer.name}"
        assert t_1_out_c >= 0, f"Heat Exchanger {self.name} t_1_out_c is negative ({t_1_out_c}) for timestep {self.time} in prosumer {prosumer.name}"
        assert t_1_in_c >= 0, f"Heat Exchanger {self.name} t_1_in_c is negative ({t_1_in_c}) for timestep {self.time} in prosumer {prosumer.name}"
        assert mdot_2_kg_per_s >= 0, f"Heat Exchanger {self.name} mdot_2_kg_per_s is negative ({mdot_2_kg_per_s}) for timestep {self.time} in prosumer {prosumer.name}"
        assert mdot_1_kg_per_s >= 0, f"Heat Exchanger {self.name} mdot_1_kg_per_s is negative ({mdot_1_kg_per_s}) for timestep {self.time} in prosumer {prosumer.name}"
        assert t_1_out_c <= t_1_in_c, f"Heat Exchanger {self.name} t_1_out_c > t_1_in_c ({t_1_out_c} > {t_1_in_c}) for timestep {self.time} in prosumer {prosumer.name}"
        assert t_2_out_c >= t_2_in_c, f"Heat Exchanger {self.name} t_2_out_c < t_2_in_c ({t_2_out_c} < {t_2_in_c}) for timestep {self.time} in prosumer {prosumer.name}"

        if np.isnan(self.t_keep_return_c) or mdot_1_kg_per_s == 0 or abs(t_1_out_c - self.t_keep_return_c) < TEMPERATURE_CONVERGENCE_THRESHOLD_C:  # or len(self._get_mapped_initiators_on_same_level(prosumer)) == 0:
            # If the actual output temperature is the same as the promised one, the storage is correctly applied
            self.finalize(prosumer, result, result_fluid_mix)
            self.applied = True
            self.t_previous_1_out_c = np.nan
            self.t_previous_1_in_c = np.nan
            self.mdot_previous_1_kg_per_s = np.nan
        else:
            # Else, reapply the upstream controllers with the new temperature so no energy appears or disappears
            # FixMe: Should not do that if the initiators is not on the same level
            self._unapply_initiators(prosumer)
            self.t_previous_1_out_c = t_1_out_c
            self.t_previous_1_in_c = t_1_in_c
            self.mdot_previous_1_kg_per_s = mdot_1_kg_per_s
            self.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: np.nan,
                                              FluidMixMapping.MASS_FLOW_KEY: np.nan}
