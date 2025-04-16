from pandaprosumer.controller.mapped import MappedController
import numpy as np


class ReadPipeProdControl(MappedController):
    """
        ReadPipeProdControl

        Read the temperature at the first element and the mass flow at the second element in the net.
        Write these data to the output for mapping
    """

    @classmethod
    def name(cls):
        return "read_pipe_controller"

    def __init__(self, net, heat_producer_data, in_service=True,
                 recycle=False, order=0, level=0, **kwargs):
        super().__init__(net, heat_producer_data, in_service=in_service, order=order, level=level, **kwargs)

    def control_step(self, net):
        super().control_step(net)

        ret_jct_id = net[self.element_name]['return_junction'].values[0]
        t_c = net.res_junction.loc[ret_jct_id]['t_k'] - 273.15
        feed_jct_id = net[self.element_name]['flow_junction'].values[0]
        tflow_c = net.res_junction.loc[feed_jct_id]['t_k'] - 273.15
        mdot_kg_per_s = net['res_'+self.element_name].loc[self.element_index, "mdot_from_kg_per_s"].values[0]

        result = np.array([[t_c, tflow_c, mdot_kg_per_s]])

        self.finalize(net, result)

        self.applied = True
