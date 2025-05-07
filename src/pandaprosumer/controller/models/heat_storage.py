"""
Module containing the HeatStorageController class.
"""

import numpy as np
import pandas as pd

from pandaprosumer.controller.base import BasicProsumerController


class HeatStorageController(BasicProsumerController):
    """
    Controller for heat storage systems.
    """

    def name_class(self):
        return "heat_storage_controller"

    def __init__(self, prosumer, heat_storage_object, order, level, init_soc=0., in_service=True, index=None, **kwargs):
        """
        Initializes the HeatStorageController.

        :param prosumer: The prosumer object
        :param heat_storage_object: The heat storage object
        :param order: The order of the controller
        :param level: The level of the controller
        :param init_soc: Initial state of charge
        :param in_service: The in-service status of the controller
        :param index: The index of the controller
        :param kwargs: Additional keyword arguments
        """
        super().__init__(prosumer, heat_storage_object, order=order, level=level, in_service=in_service, index=index, **kwargs)
        self._soc = float(init_soc)

    def q_to_receive_kw(self, prosumer):
        """
        Calculates the heat to receive in kW.

        :param prosumer: The prosumer object
        :return: Heat to receive in kW
        """
        self.applied = False
        _q_capacity_kwh = self._get_element_param(prosumer, "q_capacity_kwh")
        fill_level_kwh = min(self._soc, 1) * _q_capacity_kwh
        q_to_receive_kw = (_q_capacity_kwh - fill_level_kwh) * 3600 / self.resol
        q_to_receive_kw += self.q_to_deliver_kw(prosumer)
        if not np.isnan(self._get_input('q_received_kw')):
            # If there is already some power in the input, don't require it again
            q_received_kw = self._get_input('q_received_kw')
            q_to_receive_kw -= q_received_kw
            q_to_receive_kw = max(0., q_to_receive_kw)
        return q_to_receive_kw

    def q_to_deliver_kw(self, prosumer):
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
        q_to_deliver_kw = self.q_to_deliver_kw(prosumer)
        _q_capacity_kwh = self._get_element_param(prosumer, "q_capacity_kwh")
        e_received_kwh = self._get_input("q_received_kw") * self.resol / 3600
        potential_kwh = self._soc * _q_capacity_kwh + e_received_kwh
        demand_kwh = q_to_deliver_kw * self.resol / 3600
        if demand_kwh > potential_kwh:
            # Cannot meet the demand
            demand_kwh = potential_kwh
        if not isinstance(demand_kwh, np.ndarray) and demand_kwh == 0:
            demand_kwh = np.array([0.]) / self.resol / 3600
        fill_level_kwh = potential_kwh - demand_kwh

        excess_energy_kwh = max(0, fill_level_kwh - _q_capacity_kwh)
        if excess_energy_kwh > 0:
            raise ValueError(f"Excess energy detected: {excess_energy_kwh} kWh exceeds the maximum capacity.")

        self._soc = fill_level_kwh / _q_capacity_kwh
        demand_kw = demand_kwh / (self.resol / 3600)
        assert 0 <= self._soc <= 1, (f"SOC = {self._soc} invalid for controller {self.name} in prosumer {prosumer.name}"
                                     f"at timestep {self.time}")
        result = np.array([pd.Series(self._soc), pd.Series(demand_kw)])
        self.finalize(prosumer, result.T)
        self.applied = True
