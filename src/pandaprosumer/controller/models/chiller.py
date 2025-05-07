import numpy as np
import pandas as pd
from CoolProp.CoolProp import PropsSI
from pandaprosumer.controller.base import BasicProsumerController

class ChillerController(BasicProsumerController):
    """Definition of the Class for the Controller"""

    def name_class(self):
        """Name of the chiller"""
        return "sn_chiller_controller"

    def __init__(self, prosumer, sn_chiller_object, order, level, data_source=None, in_service=True, index=None,
                 name=None, **kwargs):
        """Initialise the attributes of the object"""
        super(ChillerController, self).__init__(
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
        #self.element_instance = prosumer[self.element].loc[self.element_index, :]
        # After initializing element_instance
        self.element_instance = prosumer[self.element].loc[self.element_index, :]
        print("Element Instance Shape:", self.element_instance.shape)
        self.res = np.zeros([len(self.element_index), len(self.time_index), len(self.result_columns)])
        self.step_results = np.full([len(self.element_index), len(self.obj.result_columns)], np.nan)
        self.time = None
        self.applied = None

    @property
    def _t_set_pt_c(self):
        return self._get_input("t_set_pt_c")

    @property
    def _t_in_ev_c(self):
        return self._get_input("t_in_ev_c")

    @property
    def _t_in_cond_c(self):
        return self._get_input("t_in_cond_c")

    @property
    def _dt_cond_c(self):
        return self._get_input("dt_cond_c")

    @property
    def _n_is(self):
        return self._get_input("n_is")

    @property
    def _q_max_kw(self):
        return self._get_input("q_max_kw")

    @property
    def _ctrl(self):
        return self._get_input("ctrl")

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
        print(f"Chiller activation check:")
        print(f"  _ctrl: {self._ctrl}")
        print(f"  q_to_deliver_kw: {self.q_to_deliver_kw(prosumer)}")
        print(f"  _t_set_pt_c: {self._t_set_pt_c}")
        print(f"  _t_in_ev_c: {self._t_in_ev_c}")
        if self._ctrl == 0 or self.q_to_deliver_kw(prosumer) <= 0.0 or self._t_set_pt_c >= self._t_in_ev_c:
            t_out_cond_in_c = self._t_in_cond_c
            t_out_ev_in_c = self._t_in_ev_c


            result = (
                np.array([0.0]),
                np.array([0.0]),
                np.array([0.0]),
                np.array([0.0]),
                np.array([0.0]),
                np.array([t_out_ev_in_c]).flatten(),
                np.array([t_out_cond_in_c]).flatten(),
                np.array([0.0]),
                np.array([0.0]),
                np.array([0.0]),
            )


            for idx, series in enumerate(result):
                print(f"Shape of result[{idx}]: {series.shape}")


            array = np.stack(result, axis=0)


            self.finalize(prosumer, array.T)  # Transpose to match expected output format
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

            array = np.array(result).reshape(1, -1)  # Shape (1, 10)
            self.finalize(prosumer, array)  # Transpose to match expected output format
            self.applied = True


            # for j, mapping in enumerate(zip(self.element_index, self.obj.assigned_object)):
            #     print(self.obj.assigned_object)
            #     el_idx, ass_obj = mapping
            #     ass_obj.control_strategy(
            #         prosumer=prosumer, obj=self.obj, assigned_obj=ass_obj
            # )

        # set the "convergence condition" to tell the system that this controller is finished
        # self.applied = True
