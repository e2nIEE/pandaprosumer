import pandas as pd
import logging
import numpy as np

from pandaprosumer.controller.base import BasicProsumerController

logging.basicConfig(level=logging.WARNING)


"""
Module containing the HeatPumpController class.
"""


class BoosterHeatPumpController(BasicProsumerController):
    """
    Controller for heat pumps.
    """

    @classmethod
    def name(cls):
        return "booster_heat_pump"

    def __init__(self, prosumer, heat_pump_object, order, level, in_service=True, index=None, **kwargs):
        """
        Initializes the HeatPumpController.

        :param prosumer: The prosumer object
        :param heat_pump_object: The heat pump object
        :param order: The order of the controller
        :param level: The level of the controller
        :param in_service: The in-service status of the controller
        :param index: The index of the controller
        :param kwargs: Additional keyword arguments
        """
        super().__init__(prosumer, heat_pump_object, order=order, level=level, in_service=in_service, index=index, **kwargs)

    @property
    def _t_source(self):
        return self._get_input("t_source_k")

    @property
    def _t_sink(self):
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
        super().control_step(prosumer)
        demand_kw = self.q_requested_kw(prosumer)
        p_el_kw = self._p_received_kw
        q_kw = self._q_received_kw
        t_source_k = self._t_source
        t_sink_k = self._t_sink
        hp_type = self._get_element_param(prosumer, "hp_type")
        mode = self._mode

        t_source_k = t_source_k - 273.0
        t_sink_k = t_sink_k - 273.0

        if hp_type == "water-water-sdewes":
            t_min_source_k = 60.0
            t_max_source_k = 99.1
            cop_coeff = [11.05, -0.15]
        else:
            raise ValueError(f"Unknown heat pump type: {hp_type}")


        if mode == 3: # Mode 1: total heat is source heat plus heat generated (boosting)
            if hp_type == 'water-water-sdewes':
                if t_source_k > t_max_source_k or t_source_k < t_min_source_k:
                    cop = 0
                    p_el_kw = 0
                    q_kw = 0
                    q_remain_kw = demand_kw
                    logging.warning(f"Heat pump is not operating due to the heat source "
                                    f"temperature being out of range: {float(t_source_k)} celsius")
                else:
                    q_max_kw = 647.6 + 15.76 * t_source_k
                    q_remain_kw, q_kw, cop, p_el_kw = self.third_mode_calc(demand_kw, q_max_kw, t_source_k, t_sink_k, cop_coeff)

            else:
                raise ValueError(f"Wrong type: {mode}")
        else:
            raise ValueError(f"Wrong mode: {mode}")

        result = np.array([pd.Series(cop),
                  pd.Series(q_kw),
                  pd.Series(q_remain_kw),
                  pd.Series(p_el_kw)
                  ])

        self.finalize(prosumer, result.T)

        self.applied = True

    def first_mode_calc(self, demand_kw, q_kw, q_max_kw, p_el_kw, t_source_k, a):
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
        cop = a[0] + a[1] * t_source_k
        q_kw_1 = p_el_kw * cop + q_kw if p_el_kw * cop + q_kw < q_max_kw else q_max_kw


        return q_remain_kw, q_kw_1, cop

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
        cop_floor = cop_coeff[0] + cop_coeff[1] * (t_sink_floor_heating_k - t_source_k) + cop_coeff[2] * (
                t_sink_floor_heating_k - t_source_k) ** 2
        cop_radiator = cop_coeff[0] + cop_coeff[1] * (t_sink_radiator_heating_k - t_source_k) + cop_coeff[2] * (
                t_sink_floor_heating_k - t_source_k) ** 2
        q_floor_kw = p_el_kw * cop_floor if p_el_kw * cop_floor < q_max_kw else q_max_kw
        q_radiator_kw = p_el_kw * cop_radiator if p_el_kw * cop_radiator < q_max_kw else q_max_kw
        return q_remain_kw, q_floor_kw, q_radiator_kw, cop_floor, cop_radiator

    def third_mode_calc(self, demand_kw, q_max_kw, t_source_k, t_sink_k, cop_coeff):

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
            - pel_floor_kw - Electrical power for the floor heating in kW
            - pel_radiator_kw - Electrical power for the radiator heating in kW
            - q_floor_kw - Heat for the floor heating in kW
            - q_radiator_kw - Heat for the radiator heating in kW
        """


        cop = cop_coeff[0] + cop_coeff[1] * (t_sink_k - t_source_k)

        if demand_kw > q_max_kw:
            q_remain_kw = demand_kw - q_max_kw
            p_el_kw = q_max_kw / cop
            q_kw = q_max_kw
            return q_remain_kw, q_kw, cop, p_el_kw
        else:
            q_remain_kw = 0
            p_el_kw = demand_kw / cop
            return q_remain_kw, demand_kw, cop, p_el_kw
