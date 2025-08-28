import numpy as np
from .base import BasicProsumerController
from pandaprosumer.mapping import FluidMixMapping
from pandaprosumer.constants import CELSIUS_TO_K

class GenericToFluidMixController(BasicProsumerController):

    def __init__(self, prosumer, converter_object, order, level, in_service=True, index=None, **kwargs):

        super().__init__(prosumer, basic_prosumer_object=converter_object, order=order, level=level, in_service=in_service, index=index, **kwargs)
        self.fluid = prosumer.fluid


    def t_m_to_q_kw(self,
                    mdot, t_in, t_out) -> float:
        """
        Calculate the thermal power from massflow and temperature difference
        """

        if mdot is None or np.isnan(mdot) or mdot <= 0:
            return 0.0

        t_mean_K = CELSIUS_TO_K + 0.5 * (t_in + t_out)
        cp = self.fluid.get_heat_capacity(t_mean_K)
        return mdot * cp * (t_in - t_out) / 1e3

    def q_to_receive_kw(self, prosumer):
        """
        Calculates the heat to receive in kW.

        :param prosumer: The prosumer object
        :return: Heat to receive in kW
        """
        self.applied = False
        q_to_receive_kw = 0.
        for responder in self._get_mapped_responders(prosumer):

            t_required_in_c, t_required_out_c, mdot_required_kg_per_s = responder._t_m_to_receive_init(prosumer)

            q_required_kw = self.t_m_to_q_kw(mdot_required_kg_per_s, t_required_in_c, t_required_out_c)
            q_to_receive_kw += q_required_kw

        return q_to_receive_kw

    def control_step(self, prosumer):

        t_supply_c = self._get_input("t_supply_c")
        t_required_out_c, t_required_in_c, mdot_required_tab_kg_per_s = self.t_m_to_deliver(prosumer)#, t_feed_c=t_supply_c)
        #print(t_required_out_c, t_required_in_c, mdot_required_tab_kg_per_s)
        mdot_required_kg_per_s = np.sum(mdot_required_tab_kg_per_s)
        deltaT = t_supply_c - t_required_in_c

        q_received_kw = self._get_input('q_received_kw')
        #print(q_received_kw)
        if abs(deltaT) < 1e-6:
            mdot_received_kg_per_s = 0.0
        else:
            t_mean_K = CELSIUS_TO_K + 0.5 * (t_supply_c + t_required_in_c)
            cp = self.fluid.get_heat_capacity(t_mean_K)
            mdot_received_kg_per_s = q_received_kw * 1e3/ (cp * deltaT)
            #print(mdot_received_kg_per_s)

        result = np.array([])

        result_fluid_mix = []
        result_fluid_mix.append({FluidMixMapping.TEMPERATURE_KEY: t_supply_c,
                                 FluidMixMapping.MASS_FLOW_KEY: mdot_received_kg_per_s})

        self.finalize(prosumer, result, result_fluid_mix)
        self.applied = True