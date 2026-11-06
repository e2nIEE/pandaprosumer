import pandas as pd
import logging
import numpy as np

from pandaprosumer.constants import CELSIUS_TO_K
from pandaprosumer.controller.base import BasicProsumerController

logging.basicConfig(level=logging.WARNING)

#: Smallest temperature lift [K] the COP correlations are evaluated at. They are quadratic fits that run away
#: for small (or negative) lifts: a 3 K lift gave a COP of 20.7 on ``water-water2``. Below this lift the
#: heat pump still has to drive its own refrigerant cycle, so it gets the COP of this lift.
MIN_LIFT_K = 15.0


def booster_cop(t_sink_c, t_source_c, cop_coeff):
    """
    COP of a booster heat pump for a sink and a source temperature [°C]: ``a0 + a1·ΔT + a2·ΔT²``, with the lift
    ``ΔT = t_sink − t_source`` held between ``MIN_LIFT_K`` and the lift where the fit is lowest (beyond it the
    ``water-water`` fits rise again, a COP growing with the lift).

    :param t_sink_c: Sink temperature in °C
    :param t_source_c: Source temperature in °C
    :param cop_coeff: The fit's coefficients ``[a0, a1, a2]``
    :return: The COP
    """
    a0, a1, a2 = cop_coeff
    lift_k = max(t_sink_c - t_source_c, MIN_LIFT_K)
    if a2 > 0:
        lift_k = min(lift_k, max(-a1 / (2 * a2), MIN_LIFT_K))
    return a0 + a1 * lift_k + a2 * lift_k ** 2


"""
Module containing the BoosterHeatPumpController class.
"""


class BoosterHeatPumpController(BasicProsumerController):
    """
    Controller for booster heat pumps.
    """

    def name_class(self):
        return "booster_heat_pump_controller"

    def __init__(self, prosumer, booster_heat_pump_controller_data, order, level, in_service=True, index=None, **kwargs):
        """
        Initializes the BoosterHeatPumpController.

        :param prosumer: The prosumer object
        :param booster_heat_pump_controller_data: The booster heat pump controller data object (e.g. BoosterHeatPumpControllerData)
        :param order: The order of the controller
        :param level: The level of the controller
        :param in_service: The in-service status of the controller
        :param index: The index of the controller
        :param kwargs: Additional keyword arguments
        """
        super().__init__(prosumer, booster_heat_pump_controller_data, order=order, level=level, in_service=in_service, index=index, **kwargs)

    @property
    def _t_amb_k(self):
        return self._get_input("t_amb_k")

    @property
    def _t_source_k(self):
        return self._get_input("t_source_k")

    @property
    def _t_sink_k(self):
        return self._get_input("t_sink_k")

    @property
    def _mode(self):
        return self._get_input("mode")

    @property
    def _q_received_kw(self):
        return self._get_input("q_received_kw")

    @property
    def _p_received_kw(self):
        return self._get_input("p_received_kw")


    def q_to_receive_kw(self, prosumer):
        """
        Calculates the heat to receive in kW.

        :param prosumer: The prosumer object
        :return: Heat to receive in kW
        """
        self.applied = False
        q_to_receive_kw = 0.
        for responder in self._get_generic_mapped_responders(prosumer):
            q_to_receive_kw += responder.q_to_receive_kw(prosumer)
        return q_to_receive_kw

    def p_to_receive_kw(self, prosumer):
        """
        Calculates the power to receive in kW.

        :param prosumer: The prosumer object
        :return: Power to receive in kW
        """
        self.applied = False
        p_to_receive_kw = 0.
        for responder in self._get_generic_mapped_responders(prosumer):
            p_to_receive_kw += responder.p_to_receive_kw(prosumer)
        return p_to_receive_kw

    def q_requested_kw(self, prosumer):
        """
        Calculates the heat to deliver in kW.

        :param prosumer: The prosumer object
        :return: Heat to deliver in kW
        """
        q_to_deliver_kw = 0.
        for responder in self._get_generic_mapped_responders(prosumer):
            q_to_deliver_kw += responder.q_to_receive_kw(prosumer)
        return q_to_deliver_kw

    def control_step(self, prosumer):
        """
        Executes the control step for the controller.

        :param prosumer: The prosumer object
        """
        if not (self.in_service and getattr(prosumer, self.obj.element_name).iloc[self.obj.element_index[0]].in_service):
            self.applied = True
            return
        super().control_step(prosumer)
        demand_kw = self.q_requested_kw(prosumer)
        p_el_kw = self._p_received_kw
        q_kw = self._q_received_kw
        t_amb_k = self._t_amb_k
        t_source_k = self._t_source_k
        t_sink_k = self._t_sink_k
        bhp_type = self._get_element_param(prosumer, "bhp_type")
        mode = self._mode
        q_max_kw = self._get_element_param(prosumer, "q_max_kw")

        t_source_k = t_source_k - CELSIUS_TO_K  # in celsius
        t_amb_k = t_amb_k - CELSIUS_TO_K  # in celsius

        if bhp_type == "air-water":
            t_min_source_k = -25.0
            t_max_source_k = 45.0
            cop_coeff = [5.06, -0.05, 0.00006]
            if np.isnan(t_sink_k):
                t_sink_floor_heating_k = 30.0 - 0.5 * t_amb_k
                t_sink_radiator_heating_k = 40.0 - 1.0 * t_amb_k
            else:
                t_sink_floor_heating_k = t_sink_k - CELSIUS_TO_K
                t_sink_radiator_heating_k = t_sink_k - CELSIUS_TO_K
            if pd.isna(q_max_kw):
                q_max_kw = 5.8 + 0.21 * t_source_k
        elif bhp_type == "water-water1":
            t_min_source_k = -10.0
            t_max_source_k = 25.0
            cop_coeff = [5.06, -0.05, 0.00006]
            if np.isnan(t_sink_k):
                t_sink_floor_heating_k = 30.0 - 0.5 * t_amb_k
                t_sink_radiator_heating_k = 40.0 - 1.0 * t_amb_k
            else:
                t_sink_floor_heating_k = t_sink_k - CELSIUS_TO_K
                t_sink_radiator_heating_k = t_sink_k - CELSIUS_TO_K
            if pd.isna(q_max_kw):
                q_max_kw = 5.8 + 0.21 * t_source_k
        elif bhp_type == "water-water2":
            t_min_source_k = 10.0
            t_max_source_k = 80.0
            cop_coeff = [23.69, -0.986, 0.012]
            if np.isnan(t_sink_k):
                t_sink_floor_heating_k = 30.0 - 0.5 * t_amb_k
                t_sink_radiator_heating_k = 40.0 - 1.0 * t_amb_k
            else:
                t_sink_floor_heating_k = t_sink_k - CELSIUS_TO_K
                t_sink_radiator_heating_k = t_sink_k - CELSIUS_TO_K
            if pd.isna(q_max_kw):
                q_max_kw = 25.308 + 0.963 * t_source_k
        elif bhp_type == "water-water3":
            t_min_source_k = 10.0
            t_max_source_k = 80.0
            cop_coeff = [19.37, -0.757, 0.009]
            if np.isnan(t_sink_k):
                t_sink_floor_heating_k = 30.0 - 0.5 * t_amb_k
                t_sink_radiator_heating_k = 40.0 - 1.0 * t_amb_k
            else:
                t_sink_floor_heating_k = t_sink_k - CELSIUS_TO_K
                t_sink_radiator_heating_k = t_sink_k - CELSIUS_TO_K
            if pd.isna(q_max_kw):
                q_max_kw = 29.005 + 1.035 * t_source_k

        else:
            raise ValueError(f"Unknown heat pump type: {bhp_type}")

        if mode in [1, 2, 3]:
            if mode == 1: # Mode 1: total heat is source heat plus heat generated (boosting)
                if bhp_type == 'water-water1' or bhp_type == 'air-water':
                    if t_source_k > t_max_source_k or t_source_k < t_min_source_k:
                        cop_floor = 0
                        cop_radiator = 0
                        pel_floor_kw = 0
                        pel_radiator_kw = 0
                        q_floor_kw = 0
                        q_radiator_kw = 0
                        q_remain_kw = demand_kw
                        logging.warning(f"Heat pump is not operating due to the heat source "
                                    f"temperature being out of range: {float(t_source_k)} celsius")
                    else:
                        q_remain_kw, q_floor_kw, q_radiator_kw, cop_floor, cop_radiator = (
                            self.first_mode_calc(q_kw, demand_kw, p_el_kw, q_max_kw,
                                             t_sink_floor_heating_k, t_sink_radiator_heating_k, t_source_k, cop_coeff))
                        pel_floor_kw = p_el_kw
                        pel_radiator_kw = p_el_kw
                if bhp_type == 'water-water2':
                    if t_source_k > t_max_source_k:
                        cop_floor = 0
                        cop_radiator = 0
                        pel_floor_kw = 0
                        pel_radiator_kw = 0
                        q_floor_kw = 0
                        q_radiator_kw = 0
                        q_remain_kw = demand_kw
                        logging.warning(f"Heat pump is not operating due to the heat source "
                                        f"temperature being out of range: {float(t_source_k)} celsius")
                    else:
                        q_remain_kw, q_floor_kw, q_radiator_kw, cop_floor, cop_radiator = (
                            self.first_mode_calc(q_kw, demand_kw, p_el_kw, q_max_kw,
                                                 t_sink_floor_heating_k, t_sink_radiator_heating_k, t_source_k, cop_coeff))
                        pel_floor_kw = p_el_kw
                        pel_radiator_kw = p_el_kw
                if bhp_type == 'water-water3':
                    if t_source_k > t_max_source_k:
                        cop_floor = 0
                        cop_radiator = 0
                        pel_floor_kw = 0
                        pel_radiator_kw = 0
                        q_floor_kw = 0
                        q_radiator_kw = 0
                        q_remain_kw = demand_kw
                        logging.warning(f"Heat pump is not operating due to the heat source "
                                        f"temperature being out of range: {float(t_source_k)} celsius")
                    else:

                        q_remain_kw, q_floor_kw, q_radiator_kw, cop_floor, cop_radiator = (
                            self.first_mode_calc(q_kw, demand_kw, p_el_kw, q_max_kw,
                                                 t_sink_floor_heating_k, t_sink_radiator_heating_k, t_source_k, cop_coeff))
                        pel_floor_kw = p_el_kw
                        pel_radiator_kw = p_el_kw

            if mode == 2:
                if bhp_type == 'water-water1' or bhp_type == 'air-water':# Mode 2: total heat is heat generated
                    if t_source_k > t_max_source_k or t_source_k < t_min_source_k:
                        cop_floor = 0
                        cop_radiator = 0
                        pel_floor_kw = 0
                        pel_radiator_kw = 0
                        q_floor_kw = 0
                        q_radiator_kw = 0
                        q_remain_kw = demand_kw
                        logging.warning(f"Heat pump is not operating due to the heat source "
                                    f"temperature being out of range: {float(t_source_k)} celsius")
                    else:
                        q_remain_kw, q_floor_kw, q_radiator_kw, cop_floor, cop_radiator = (
                            self.second_mode_calc(demand_kw, p_el_kw, q_max_kw,
                                              t_sink_floor_heating_k, t_sink_radiator_heating_k, t_source_k, cop_coeff))
                        pel_floor_kw = p_el_kw
                        pel_radiator_kw = p_el_kw
                if bhp_type == 'water-water2':
                    if t_source_k > t_max_source_k:
                        cop_floor = 0
                        cop_radiator = 0
                        pel_floor_kw = 0
                        pel_radiator_kw = 0
                        q_floor_kw = 0
                        q_radiator_kw = 0
                        q_remain_kw = demand_kw
                        logging.warning(f"Heat pump is not operating due to the heat source "
                                        f"temperature being out of range: {float(t_source_k)} celsius")
                    else:
                        q_remain_kw, q_floor_kw, q_radiator_kw, cop_floor, cop_radiator = (
                            self.second_mode_calc(demand_kw, p_el_kw, q_max_kw,
                                                  t_sink_floor_heating_k, t_sink_radiator_heating_k, t_source_k, cop_coeff))
                        pel_floor_kw = p_el_kw
                        pel_radiator_kw = p_el_kw
                if bhp_type == 'water-water3':
                    if t_source_k > t_max_source_k:
                        cop_floor = 0
                        cop_radiator = 0
                        pel_floor_kw = 0
                        pel_radiator_kw = 0
                        q_floor_kw = 0
                        q_radiator_kw = 0
                        q_remain_kw = demand_kw
                        logging.warning(f"Heat pump is not operating due to the heat source "
                                        f"temperature being out of range: {float(t_source_k)} celsius")
                    else:
                        q_remain_kw, q_floor_kw, q_radiator_kw, cop_floor, cop_radiator = (
                            self.second_mode_calc(demand_kw, p_el_kw, q_max_kw,
                                                  t_sink_floor_heating_k, t_sink_radiator_heating_k, t_source_k, cop_coeff))
                        pel_floor_kw = p_el_kw
                        pel_radiator_kw = p_el_kw
            if mode == 3:
                if bhp_type == 'water-water1' or bhp_type == 'air-water':# Mode 3: produced heat is a result of infinite electrical source, produced heat is either q_max_kw or demand_kw
                    if t_source_k > t_max_source_k or t_source_k < t_min_source_k:
                        cop_floor = 0
                        cop_radiator = 0
                        pel_floor_kw = 0
                        pel_radiator_kw = 0
                        q_floor_kw = 0
                        q_radiator_kw = 0
                        q_remain_kw = demand_kw
                        logging.warning(f"Heat pump is not operating due to the heat source "
                                        f"temperature being out of range: {float(t_source_k)} celsius")
                    else:
                        q_remain_kw, cop_floor, cop_radiator, pel_floor_kw, pel_radiator_kw, q_floor_kw, q_radiator_kw \
                            = self.third_mode_calc(demand_kw, q_max_kw, t_sink_floor_heating_k, t_sink_radiator_heating_k, t_source_k, cop_coeff)
                if bhp_type == 'water-water2':
                    if t_source_k > t_max_source_k:
                        cop_floor = 0
                        cop_radiator = 0
                        pel_floor_kw = 0
                        pel_radiator_kw = 0
                        q_floor_kw = 0
                        q_radiator_kw = 0
                        q_remain_kw = demand_kw
                        logging.warning(f"Heat pump is not operating due to the heat source "
                                        f"temperature being out of range: {float(t_source_k)} celsius")
                    else:
                        q_remain_kw, cop_floor, cop_radiator, pel_floor_kw, pel_radiator_kw, q_floor_kw, q_radiator_kw \
                            = self.third_mode_calc(demand_kw, q_max_kw, t_sink_floor_heating_k,
                                                   t_sink_radiator_heating_k, t_source_k, cop_coeff)
                if bhp_type == 'water-water3':
                    if t_source_k > t_max_source_k:
                        cop_floor = 0
                        cop_radiator = 0
                        pel_floor_kw = 0
                        pel_radiator_kw = 0
                        q_floor_kw = 0
                        q_radiator_kw = 0
                        q_remain_kw = demand_kw
                        logging.warning(f"Heat pump is not operating due to the heat source "
                                        f"temperature being out of range: {float(t_source_k)} celsius")
                    else:
                        q_remain_kw, cop_floor, cop_radiator, pel_floor_kw, pel_radiator_kw, q_floor_kw, q_radiator_kw \
                            = self.third_mode_calc(demand_kw, q_max_kw, t_sink_floor_heating_k,
                                                   t_sink_radiator_heating_k, t_source_k, cop_coeff)
        else:
            raise ValueError(f"Unknown mode: {mode}")

        result = np.array([pd.Series(cop_floor),
                  pd.Series(cop_radiator),
                  pd.Series(pel_floor_kw),
                  pd.Series(pel_radiator_kw),
                  pd.Series(q_remain_kw),
                  pd.Series(q_floor_kw),
                  pd.Series(q_radiator_kw)
                  ])

        self.last_result = {
            "cop_floor": cop_floor,
            "cop_radiator": cop_radiator,
            "pel_floor_kw": pel_floor_kw,
            "pel_radiator_kw": pel_radiator_kw,
            "q_remain_kw": q_remain_kw,
            "q_floor_kw": q_floor_kw,
            "q_radiator_kw": q_radiator_kw
        }


        self.finalize(prosumer, result.T)

        self.applied = True

    def first_mode_calc(self, q_kw, demand_kw, p_el_kw, q_max_kw,
                        t_sink_floor_heating_k, t_sink_radiator_heating_k, t_source_k, cop_coeff):
        """
        Calculation of quantities for the mode 1 of the heat pump. Booster heat pump in mode 1
        takes the inputted heat and electricity from external source and boosts heat
        for the floor and radiator heating. Mode 1 also calculates the COP for the floor and radiator heating
        that is dependent on the temperature of the heat source and heat sink.

        :param q_kw: Inputted heat in kW
        :param demand_kw: Demand of heat in kW
        :param p_el_kw: Electrical power in kW
        :param q_max_kw: Maximum heat in kW
        :param t_sink_floor_heating_k: Temperature of the floor heating sink in K
        :param t_sink_radiator_heating_k: Temperature of the radiator heating sink in K
        :param t_source_k: Temperature of the heat source in K
        :param cop_coeff: Coefficients for the COP calculation
        :returns:
            - q_remain_kw - Remaining heat in kW
            - q_floor_kw - Heat for the floor heating in kW
            - q_radiator_kw - Heat for the radiator heating in kW
            - cop_floor - COP for the floor heating
            - cop_radiator - COP for the radiator heating
        """
        if demand_kw > q_max_kw:
            q_remain_kw = demand_kw - q_max_kw
        else:
            q_remain_kw = 0
        cop_floor = booster_cop(t_sink_floor_heating_k, t_source_k, cop_coeff)
        cop_radiator = booster_cop(t_sink_radiator_heating_k, t_source_k, cop_coeff)

        q_generated_floor = p_el_kw * cop_floor + q_kw
        q_generated_radiator = p_el_kw * cop_radiator + q_kw

        if q_generated_floor < q_max_kw and q_generated_floor < demand_kw:
            q_floor_kw = q_generated_floor
        else:
            q_floor_kw = min(q_max_kw, demand_kw)

        if q_generated_radiator < q_max_kw and q_generated_radiator < demand_kw:
            q_radiator_kw = q_generated_radiator
        else:
            q_radiator_kw = min(q_max_kw, demand_kw)

        return q_remain_kw, q_floor_kw, q_radiator_kw, cop_floor, cop_radiator

    def second_mode_calc(self, demand_kw, p_el_kw, q_max_kw,
                         t_sink_floor_heating_k, t_sink_radiator_heating_k, t_source_k, cop_coeff):
        """
        Calculation of quantities for the mode 2 of the heat pump. Booster heat pump in mode 2
        takes the inputted electricity from external source and produces heat
        for the floor and radiator heating. Mode 2 also calculates the COP for the floor and radiator heating
        that is dependent on the temperature of the heat source and heat sink.

        :param demand_kw: Demand of heat in kW
        :param p_el_kw: Electrical power in kW
        :param q_max_kw: Maximum heat in kW
        :param t_sink_floor_heating_k: Temperature of the floor heating sink in K
        :param t_sink_radiator_heating_k: Temperature of the radiator heating sink in K
        :param t_source_k: Temperature of the heat source in K
        :param cop_coeff: Coefficients for the COP calculation
        :returns:
            - q_remain_kw - Remaining heat in kW
            - q_floor_kw - Heat for the floor heating in kW
            - q_radiator_kw - Heat for the radiator heating in kW
            - cop_floor - COP for the floor heating
            - cop_radiator - COP for the radiator heating
        """

        if demand_kw > q_max_kw:
            q_remain_kw = demand_kw - q_max_kw
        else:
            q_remain_kw = 0
        cop_floor = booster_cop(t_sink_floor_heating_k, t_source_k, cop_coeff)
        cop_radiator = booster_cop(t_sink_radiator_heating_k, t_source_k, cop_coeff)

        q_generated_floor = p_el_kw * cop_floor
        q_generated_radiator = p_el_kw * cop_radiator

        if q_generated_floor < q_max_kw and q_generated_floor < demand_kw:
            q_floor_kw = q_generated_floor
        else:
            q_floor_kw = min(q_max_kw, demand_kw)

        if q_generated_radiator < q_max_kw and q_generated_radiator < demand_kw:
            q_radiator_kw = q_generated_radiator
        else:
            q_radiator_kw = min(q_max_kw, demand_kw)

        return q_remain_kw, q_floor_kw, q_radiator_kw, cop_floor, cop_radiator

    def third_mode_calc(self, demand_kw, q_max_kw, t_sink_floor_heating_k, t_sink_radiator_heating_k, t_source_k, cop_coeff):

        """
        Calculation of quantities for the mode 3 of the heat pump. Mode 3
        calculates the inputted electricity from infinite source (grid etc.) based on the heat demand and produces heat
        for the floor and radiator heating. Mode 3 also calculates the COP for the floor and radiator heating
        that is dependent on the temperature of the heat source and heat sink.

        :param demand_kw: Demand of heat in kW
        :param q_max_kw: Maximum heat in kW
        :param t_sink_floor_heating_k: Temperature of the floor heating sink in K
        :param t_sink_radiator_heating_k: Temperature of the radiator heating sink in K
        :param t_source_k: Temperature of the heat source in K
        :param cop_coeff: Coefficients for the COP calculation
        :returns:
            - q_remain_kw - Remaining heat in kW
            - cop_floor - COP for the floor heating
            - cop_radiator - COP for the radiator heating
            - pel_floor_kw - Electrical power needed for the floor heating in kW
            - pel_radiator_kw - Electrical power needed for the radiator heating in kW
            - q_floor_kw - Heat for the floor heating in kW
            - q_radiator_kw - Heat for the radiator heating in kW
        """


        cop_floor = booster_cop(t_sink_floor_heating_k, t_source_k, cop_coeff)
        cop_radiator = booster_cop(t_sink_radiator_heating_k, t_source_k, cop_coeff)

        if demand_kw > q_max_kw:
            q_remain_kw = demand_kw - q_max_kw
            pel_floor_kw = q_max_kw / cop_floor
            pel_radiator_kw =  q_max_kw / cop_radiator
            q_floor_kw = q_max_kw
            q_radiator_kw = q_max_kw
            return q_remain_kw, cop_floor, cop_radiator, pel_floor_kw, pel_radiator_kw, q_floor_kw, q_radiator_kw
        else:
            q_remain_kw = 0
            pel_floor_kw = demand_kw / cop_floor
            pel_radiator_kw = demand_kw / cop_radiator
            q_floor_kw = demand_kw
            q_radiator_kw = demand_kw
            return q_remain_kw, cop_floor, cop_radiator, pel_floor_kw, pel_radiator_kw, q_floor_kw, q_radiator_kw