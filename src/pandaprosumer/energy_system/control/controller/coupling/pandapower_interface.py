from pandaprosumer.controller.mapped import MappedController


class LoadControl(MappedController):
    """
        LoadControl

        Mapped input: p_in_kw (power in kW)

        Control step: Write the power to the element 'p_mw' property (converting kW to MW)

        Note: Can directly be used as a static generator controller if element_name is 'sgen' instead of 'load'
    """

    @classmethod
    def name(cls):
        return "pandapower_load_controller"

    def __init__(self, net, load_ctrl_object, in_service=True,
                 recycle=False, order=0, level=0, **kwargs):
        super().__init__(net, load_ctrl_object, in_service=in_service, order=order, level=level, **kwargs)

    @property
    def _p_in_kw(self):
        return self.inputs[:, self.input_columns.index("p_in_kw")]

    def control_step(self, net):
        super().control_step(net)
        net[self.element_name].loc[self.element_index, "p_mw"] = self._p_in_kw.sum() / 1000

        self.finalize(net, [])

        self.applied = True
