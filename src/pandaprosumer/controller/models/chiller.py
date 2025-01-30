import numpy as np
import pandas as pd
from CoolProp.CoolProp import PropsSI

"""
Module containing the ChillerController class.
"""

from pandaprosumer.controller.base import BasicProsumerController


class SenergyNetsChillerController(BasicProsumerController):
    """Definition of the Class for the Controller"""

    @classmethod
    def name(cls):
        """Name of the chiller"""
        return "sn_chiller"

    def __init__(self, prosumer, sn_chiller_object, order, level, data_source=None, in_service=True, index=None,
                 name=None,
                 **kwargs):
        """Initialise the attributes of the object

        Parameters
        ----------
        prosumer : object of type prosumer
            Prosumer container
        chiller_object : _object of type SenergyNetsChillerController
            Chiller object, where chiller inputs are defined
        data_source : object of type pandas.DataFrame
            Dataset with pandas format
        order : list
            _description_
        level :list
            _description_
        in_service : bool, optional
            _description_, by default True
        index : _type_, optional
            _description_, by default None
        """
        super(SenergyNetsChillerController, self).__init__(
            prosumer,
            basic_prosumer_object=sn_chiller_object,
            order=order,
            level=level,
            data_source=data_source,
            in_service=in_service,
            index=index,
            name=name,
            **kwargs,
        )

        self.obj = sn_chiller_object
        self.element = self.obj.element_name
        self.element_index = self.obj.element_index
        self.input_columns = self.obj.input_columns
        self.element_instance = prosumer[self.element].loc[self.element_index, :]
        self.res = np.zeros([len(self.element_index), len(self.time_index), len(self.result_columns)])
        self.step_results = np.full([len(self.element_index), len(self.obj.result_columns)], np.nan)
        self.time = None
        self.applied = None

        # time series
        # PM: check if these variable names are used in control step
        # self.pn_t_set = self.obj.profile_name_t_set_k
        # self.pn_t_in_ev = self.obj.profile_name_t_in_ev_k
        # self.pn_t_in_cond = self.obj.profile_name_t_in_cond_k
        # self.pn_dt_cond = self.obj.profile_name_dt_cond_k
        # self.pn_q_load = self.obj.profile_name_q_load_kj_per_h
        # self.pn_n_is = self.obj.profile_name_n_is
        # self.pn_q_max = self.obj.profile_name_q_max_kj_per_h
        # self.pn_ctrl = self.obj.profile_name_ctrl

    @property
    def _t_set_pt_c(self):
        return self.inputs[:, self.input_columns.index("t_set_pt_c")]

    @property
    def _t_in_ev_c(self):
        return self.inputs[:, self.input_columns.index("t_in_ev_c")]

    @property
    def _t_in_cond_c(self):
        return self.inputs[:, self.input_columns.index("t_in_cond_c")]

    @property
    def _dt_cond_c(self):
        return self.inputs[:, self.input_columns.index("dt_cond_c")]

    # @property
    # def _q_load_kw(self):
    # return self.inputs[:, self.input_columns.index("q_load_kw")]

    @property
    def _n_is(self):
        return self.inputs[:, self.input_columns.index("n_is")]

    @property
    def _q_max_kw(self):
        return self.inputs[:, self.input_columns.index("q_max_kw")]

    @property
    def _ctrl(self):
        return self.inputs[:, self.input_columns.index("ctrl")]

    def q_to_deliver_kw(self, prosumer):
        """
        Calculates the heat to deliver in kW.

        :param prosumer: The prosumer object
        :return: Heat to deliver in kW
        """
        q_to_deliver_kw = 0.
        for responder in self._get_mapped_responders(prosumer):
            q_to_deliver_kw += responder.q_to_receive_kw(prosumer)
        return q_to_deliver_kw

    def time_step(self, prosumer, time):
        """It is the first call in each time step, thus suited for things like
        reading profiles or prepare the controller for the next control step.

        .. note:: This method is ONLY being called during time-series simulation!

        :param prosumer:
        :param time:


        """
        super().time_step(prosumer, time)
        self.step_results = np.full([len(self.element_index), len(self.obj.result_columns)], np.nan)
        self.time = time
        self.applied = False

    def initialize_control(self, container):
        """Some controller require extended initialization in respect to the
        current state of the net (or their view of it). This method is being
        called after an initial loadflow but BEFORE any control strategies are
        being applied.

        This method may be interesting if you are aiming for a global
        controller or if it has to be aware of its initial state.

        :param container:


        """
        super().initialize_control(container)

    def is_converged(self, container):
        """This method calculated whether or not the controller converged. This is
        where any target values are being calculated and compared to the actual
        measurements. Returns convergence of the controller.

        :param container: _description_
        :type container: _type_


        """
        # from is_converged() in plant.py
        return self.applied

    def control_step(self, prosumer):
        """It implements the thermodynamic model of the chiller, in order to
         calculate physical properties of the refrigerants and energy consumptions
          in both the evaporator and the condenser.

        :param prosumer:


        """
        super().control_step(prosumer)
        # @tecnalia: this is where you have to put the calculation of the time series dependent values in
        # try:  # why try except here? --> because there was the
        # self.chill_inputs_validation()

        # Check the chiller is activated.
        if self._ctrl == 0 or self.q_to_deliver_kw(prosumer) <= 0.0 or self._t_set_pt_c >= self._t_in_ev_c:
            t_out_cond_in_c = self._t_in_cond_c
            t_out_ev_in_c = self._t_in_ev_c
            result = (
                np.array([0.0]),
                np.array([0.0]),
                np.array([0.0]),
                np.array([0.0]),
                np.array([0.0]),
                t_out_ev_in_c,
                t_out_cond_in_c,
                np.array([0.0]),
                np.array([0.0]),
                np.array([0.0]),
            )

            time_step_idx = np.where(self.time_index == self.time)[0][0]
            array = np.stack([series for series in result], axis=1)
            self.res[:, time_step_idx, :] = array
            self.step_results = array

            for row in self._get_mappings(prosumer):
                row.mapping.map(self, prosumer.controller.loc[row.responder].object)
            self.applied = True
        else:
            # Calculate the evaporator temperature and pressure

            t_evap = min(
                self._t_set_pt_c - self.element_instance.pp_evap[0],
                self._t_in_ev_c - self.element_instance.t_sh[0] - self.element_instance.pp_evap[0],
            )

            p_evap = PropsSI("P", "T", t_evap, "Q", 1, self.element_instance.n_ref[0])

            # Calculate the compressor inlet conditions
            t_suc = t_evap + self.element_instance.t_sh[0]
            p_suc = p_evap  # check if this exactly what in line 94

            h_suc = PropsSI("H", "T", t_suc, "P", np.array([p_suc]), self.element_instance.n_ref[0])

            s_suc = PropsSI("S", "T", t_suc, "P", np.array([p_suc]), self.element_instance.n_ref[0])

            # Calculate the condenser temperature
            t_cond = (
                    self._t_in_cond_c
                    + self._dt_cond_c
                    + self.element_instance.pp_cond[0]
                    + self.element_instance.t_sc[0]
            )

            p_cond = PropsSI("P", "T", t_cond, "Q", 1, self.element_instance.n_ref[0])

            # Calculate isentropic enthalpy
            h_is = PropsSI("H", "P", np.array([p_cond]), "S", np.array([s_suc]), self.element_instance.n_ref[0])

            # Calculate the compressor discharge conditions
            h_dis = h_suc + (h_is - h_suc) / self._n_is

            # Calculate the conditions at the output of the condenser
            h_cond_out = PropsSI(
                "H", "P", np.array([p_cond]), "T", np.array([t_cond]) - self.element_instance.t_sc[0],
                self.element_instance.n_ref[0]
            )

            # Calculate the refrigerant and water flow rates required in the condenser.
            # PM: q_load c.f. demand, q_load is q_to_deliver
            q_load_ef = min(self.q_to_deliver_kw(prosumer), self._q_max_kw)
            m_ref = q_load_ef / (h_suc - h_cond_out)
            m_cond_kg_per_s = q_load_ef / (self.element_instance.cp_water[0] * self._dt_cond_c)

            # Check if the pinchpoint at the bubble point is fulfilled; calculate the enthalpy and the water temperature at the bubble point and the water temperature
            h_bub = PropsSI("H", "P", np.array([p_cond]), "Q", 1, self.element_instance.n_ref[0])
            t_bub = self._t_in_cond_c + (
                    m_ref * (h_bub - h_cond_out) / (self.element_instance.cp_water[0] * m_cond_kg_per_s)
            )
            # PM: should this be with [0]
            if (t_bub + self.element_instance.pp_cond[0]) > t_cond:
                # The pinchpoint is not met-> Recalculate the condenser conditions, discharge and refrigerant flow rate.
                t_cond = t_bub + self.element_instance.pp_cond[0]
                p_cond = PropsSI("P", "T", t_cond, "Q", 1, self.element_instance.n_ref[0])
                h_is = PropsSI("H", "P", p_cond, "S", s_suc, self.element_instance.n_ref[0])
                h_dis = h_suc + (h_is - h_suc) / self._n_is
                h_cond_out = PropsSI(
                    "H", "P", np.array([p_cond]), "T", t_cond - self.element_instance.t_sc[0],
                    self.element_instance.n_ref[0]
                )
                m_ref = q_load_ef / (h_suc - h_cond_out)

            # calculate the compressor power consumption
            w_in_c = m_ref * (h_dis - h_suc) / self.element_instance.eng_eff[0]

            # Calculate  PLR & PLF
            plr = q_load_ef / self._q_max_kw
            # PM: check if this[0] should be retained
            plf = plr / ((self.element_instance.plf_cc[0] * plr) + (1.0 - self.element_instance.plf_cc[0]))
            w_in = w_in_c * plf

            # Calculate pumping power consumption
            # PM: same as before
            w_pump = plr * (self.element_instance.w_evap_pump[0] + self.element_instance.w_cond_pump[0])
            w_in_tot_kw = w_in + w_pump

            # Calculate the compressor discharge temperature
            t_dis = PropsSI("T", "P", np.array([p_cond]), "H", h_dis, self.element_instance.n_ref[0])

            # Calculate temperatures and water flow rates
            # PM: same as before
            q_cond_kw = m_ref * (h_dis - h_cond_out)
            m_cond_kg_per_s = q_cond_kw / (
                    self.element_instance.cp_water[0] * (self._dt_cond_c)
            )
            t_out_cond_in_c = self._t_in_cond_c + (
                    q_cond_kw / (m_cond_kg_per_s * self.element_instance.cp_water[0])
            )
            q_evap_kw = m_ref * (h_suc - h_cond_out)
            m_evap_kg_per_s = q_evap_kw / (
                    self.element_instance.cp_water[0]
                    * (self._t_in_ev_c - self._t_set_pt_c)
            )
            t_out_ev_in_c = self._t_in_ev_c - (
                    q_evap_kw / (self.element_instance.cp_water[0] * m_evap_kg_per_s)
            )

            # calculate the unmet demand and the EER
            unmet_load_kw = self.q_to_deliver_kw(prosumer) - q_evap_kw
            eer = q_evap_kw / w_in_tot_kw
            w_plf = w_in_c - w_in

            # considering other components to be connected to the cooler, please consider only the necessary outputs for your use case in Cordoba
            result = (
                q_evap_kw,
                unmet_load_kw,
                w_in_tot_kw,
                eer,
                plr,
                t_out_ev_in_c,
                t_out_cond_in_c,
                m_evap_kg_per_s,
                m_cond_kg_per_s,
                q_cond_kw,
            )

            time_step_idx = np.where(self.time_index == self.time)[0][0]
            array = np.stack([series for series in result], axis=1)
            self.res[:, time_step_idx, :] = array
            self.step_results = array

            for row in self._get_mappings(prosumer):
                row.mapping.map(self, prosumer.controller.loc[row.responder].object)

            self.applied = True
            # for j, mapping in enumerate(zip(self.element_index, self.obj.assigned_object)):
            #     print(self.obj.assigned_object)
            #     el_idx, ass_obj = mapping
            #     ass_obj.control_strategy(
            #         prosumer=prosumer, obj=self.obj, assigned_obj=ass_obj
            # )

        # set the "convergence condition" to tell the system that this controller is finished
        # self.applied = True

    def repair_control(self, container):
        """Some controllers can cause net to not converge. In this case, they can implement a method to
        try and catch the load flow error by altering some values in net, for example load scaling.
        This method is being called in the except block in run_control.
        Either implement this in a controller that is likely to cause the error, or define
        a special "load flow police" controller for your use case.

        :param container:


        """
        super().repair_control(container)

    def restore_init_state(self, container):
        """Some controllers manipulate values in net and then restore them back to initial values, e.g.
        DistributedSlack.
        This method should be used for such a purpose because it is executed in the except block of
        run_control to make sure that the net condition is restored even if load flow calculation
        doesn't converge.

        :param container:


        """
        super().restore_init_state(container)

    def finalize_control(self, container):
        """Some controller require extended finalization. This method is being
        called at the end of a loadflow.
        It is a separate method from restore_init_state because it is possible that control
        finalization does not only restore the init state but also something in addition to that,
        that would require the results in net.

        :param container:


        """
        super().finalize_control(container)
        self.inputs = np.full([len(self.element_index), len(self.obj.input_columns)], np.nan)

    def finalize_step(self, container, time):
        """After each time step, this method is being called to clean things up or
        similar. The OutputWriter is a class specifically designed to store
        results of the loadflow. If the ControlHandler.output_writer got an
        instance of this class, it will be called before the finalize step.

        :param container:
        :param time:


        """
        super().finalize_step(container, time)

    def set_active(self, container, in_service):
        """Sets the controller in or out of service.

        :param container:
        :param in_service:


        """
        super().set_active(container, in_service)

    def level_reset(self, prosumer):
        """

        :param prosumer:

        """
        pass

    # FROM PANDAPROSUMER

    def time_series_initialization(self, prosumer):
        """Initialisation of the time_series

        :param prosumer:


        """
        return super().time_series_initialization(prosumer)

    def time_series_finalization(self, prosumer):
        """Finalisation of the time series

        :param prosumer:


        """
        return self.res