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

    @classmethod
    def name(cls):
        return "heat_storage"

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

    @property
    def _q_received_kw(self):
        return self._get_input("q_received_kw")

    def q_to_receive_kw(self, prosumer):
        """
        Calculates the heat to receive in kW.

        :param prosumer: The prosumer object
        :return: Heat to receive in kW
        """
        self.applied = False
        _q_capacity_kwh = self._get_element_param(prosumer, "q_capacity_kwh")
        fill_level_kwh = self._soc * _q_capacity_kwh
        q_to_receive_kwh = _q_capacity_kwh - fill_level_kwh
        print('HS q_to_receive')
        print(fill_level_kwh)
        print(_q_capacity_kwh)
        print(q_to_receive_kwh)
        for responder in self._get_generic_mapped_responders(prosumer):
            q_to_receive_kwh += responder.q_to_receive_kw(prosumer)
        print(q_to_receive_kwh)
        return q_to_receive_kwh

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
        print("HS control_step")
        q_to_deliver_kw = self.q_to_deliver_kw(prosumer)
        _q_capacity_kwh = self._get_element_param(prosumer, "q_capacity_kwh")
        print('q_to_deliver_kw', q_to_deliver_kw)
        print('_q_capacity_kwh', _q_capacity_kwh)
        print('soc init', self._soc)
        print('resol', self.resol)
        print('self._q_received_kw', self._q_received_kw)
        e_received_kwh = self._q_received_kw * self.resol / 3600
        potential_kwh = self._soc * _q_capacity_kwh + e_received_kwh
        print('potential_kwh', potential_kwh)
        demand_kwh = q_to_deliver_kw * self.resol / 3600
        print('demand_kwh1', demand_kwh)
        if demand_kwh > potential_kwh:
            demand_kwh = potential_kwh
            print('demand_kwh2', demand_kwh)
        if not isinstance(demand_kwh, np.ndarray) and demand_kwh == 0:
            demand_kwh = np.array([0.]) / self.resol / 3600
            print('demand_kwh3', demand_kwh)
        if potential_kwh -demand_kwh > _q_capacity_kwh: # Prevent overcharging: limit stored energy to max capacity
            potential_kwh = _q_capacity_kwh + demand_kwh
        fill_level_kwh = potential_kwh - demand_kwh
        self._soc = fill_level_kwh / _q_capacity_kwh
        print('demand_kwh4', demand_kwh)
        demand_kw = demand_kwh / (self.resol / 3600)
        print('demand_kw', demand_kw)
        print('soc', self._soc)
        result = np.array([pd.Series(self._soc), pd.Series(demand_kw)])
        # Demand_kwh should be named after the delivery capacity considering the current charge status

        self.finalize(prosumer, result.T)
        self.applied = True
