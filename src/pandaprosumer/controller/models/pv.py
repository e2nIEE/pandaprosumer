import numpy as np
from pandaprosumer.controller.base import BasicProsumerController


class SenergyNetsPvProductionController(BasicProsumerController):
    """Definition of the Class for the Controller

    Parameters
    ----------
    BasicProsumerController : Object of type BasicProsumerController


    """

    @classmethod
    def name(cls):
        """Name of the PV Production time series

        """
        return "sn_pvproduction"

    def __init__(
            self,
            prosumer,
            pv_production_object,
            data_source,
            order,
            level,
            in_service=True,
            index=None,
            **kwargs,
    ):
        """Initialise the attributes of the object

        Parameters
        ----------
        prosumer : object of type prosumer
            pv_production_object container
        chiller_object : _object of type SenergyNetsChillerController
            PV Production object, where PV Production inputs are defined
        order : list
            _description_
        level :list
            _description_
        in_service : bool, optional
            _description_, by default True
        index : _type_, optional
            _description_, by default None
        """
        super().__init__(
            prosumer,
            pv_production_object,
            order=order,
            level=level,
            in_service=in_service,
            index=index,
            **kwargs,
        )

        self.element = self.obj.element
        self.element_variable = (
            self.obj.element_variable if hasattr(self.obj, "element_variable") else None
        )
        self.element_index = self.obj.element_index
        self.pros = prosumer[self.element].loc[self.element_index, :]
        self.res = np.zeros(
            [len(self.element_index), len(self.time_index), len(self.result_columns)]
        )

        self.res_step = None
        self.time = None
        self.applied = None

    def time_step(self, prosumer, time):
        """It is the first call in each time step, thus suited for things like
        reading profiles or prepare the controller for the next control step.

        .. note:: This method is ONLY being called during time-series simulation!

        Parameters
        ----------
        prosumer : object of type prosumer
            Prosumer container
        time : float
            current time step


        """
        super().time_step(prosumer, time)
        self.res_step = np.zeros(
            [len(self.element_index), len(self.obj.result_columns)]
        )
        self.time = time
        self.applied = False
        #self._p_w = self.ds.get_time_step_value(time, self.pn_p_w)
        #self._poa_direct_w_m2 = self.ds.get_time_step_value(time, self.pn_poa_direct_w_m2)
        #self._poa_sky_diffuse_w_m2 = self.ds.get_time_step_value(time, self.pn_poa_sky_diffuse_w_m2)
        #self._poa_ground_diffuse_w_m2 = self.ds.get_time_step_value(time, self.pn_poa_ground_diffuse_w_m2)
        #self._solar_elevation_deg = self.ds.get_time_step_value(time, self.pn_solar_elevation_deg)
        #self._temp_air_c = self.ds.get_time_step_value(time, self.pn_temp_air_c)
        #self._wind_speed_m_s = self.ds.get_time_step_value(time, self.pn_wind_speed_m_s)
        #self._solar_rad_reconstr_bool = self.ds.get_time_step_value(time, self.pn_solar_rad_reconstr_bool)

    def initialize_control(self, container):
        """Some controller require extended initialization in respect to the
        current state of the net (or their view of it). This method is being
        called after an initial loadflow but BEFORE any control strategies are
        being applied.

        This method may be interesting if you are aiming for a global
        controller or if it has to be aware of its initial state.

        Parameters
        ----------
        container : _type_
            _description_


        """
        super().initialize_control(container)

    def is_converged(self, container):
        """This method calculated whether or not the controller converged. This is
        where any target values are being calculated and compared to the actual
        measurements. Returns convergence of the controller.

        Parameters
        ----------
        container : _type_
            _description_

        Returns
        -------
        _type_
            _description_


        """
        # from is_converged() in plant.py
        return self.applied

    def control_step(self, prosumer):
        """It implements the thermodynamic model of the chiller, in order to
         calculate physical properties of the refrigerants and energy consumptions
          in both the evaporator and the condenser.
        Parameters
        ----------
        prosumer : object of type prosumer
            Prosumer container

        """
        super().control_step(prosumer)
        # @tecnalia: this is where you have to put the calculation of the time series dependent values in
        # try:  # why try except here? --> because there was the
        # self.chill_inputs_validation()

        # Check the chiller is activated.
        # if self._ctrl == 0 or

        # considering other components to be connected to the cooler, please consider only the necessary outputs for your use case in Cordoba
        result = (
            self._p_w,
            self._poa_direct_w_m2,
            self._poa_sky_diffuse_w_m2,
            self._poa_ground_diffuse_w_m2,
            self._solar_elevation_deg,
            self._temp_air_c,
            self._wind_speed_m_s,
            self._solar_rad_reconstr_bool,
        )

        self.finalize(prosumer, result)

        self.applied = True

    def repair_control(self, container):
        """Some controllers can cause net to not converge. In this case, they can implement a method to
        try and catch the load flow error by altering some values in net, for example load scaling.
        This method is being called in the except block in run_control.
        Either implement this in a controller that is likely to cause the error, or define
        a special "load flow police" controller for your use case.

        Parameters
        ----------
        container : _type_
            _description_


        """
        super().repair_control(container)

    def restore_init_state(self, container):
        """Some controllers manipulate values in net and then restore them back to initial values, e.g.
        DistributedSlack.
        This method should be used for such a purpose because it is executed in the except block of
        run_control to make sure that the net condition is restored even if load flow calculation
        doesn't converge.

        Parameters
        ----------
        container : _type_
            _description_


        """
        super().restore_init_state(container)

    def finalize_control(self, container):
        """Some controller require extended finalization. This method is being
        called at the end of a loadflow.
        It is a separate method from restore_init_state because it is possible that control
        finalization does not only restore the init state but also something in addition to that,
        that would require the results in net.

        Parameters
        ----------
        container : _type_
            _description_


        """
        super().finalize_control(container)

    def finalize_step(self, container, time):
        """After each time step, this method is being called to clean things up or
        similar. The OutputWriter is a class specifically designed to store
        results of the loadflow. If the ControlHandler.output_writer got an
        instance of this class, it will be called before the finalize step.

        Parameters
        ----------
        container : _type_
            _description_
        time : _type_
            _description_

        .. note:: This method is ONLY being called during time-series simulation!


        """
        super().finalize_step(container, time)

    def set_active(self, container, in_service):
        """Sets the controller in or out of service.

        Parameters
        ----------
        container : _type_
            _description_
        in_service : bool
            parameter descriving whether the chiller is in service (True, default) or not (False).


        """
        super().set_active(container, in_service)

    def level_reset(self, prosumer):
        pass

    # FROM PANDAPROSUMER

    def time_series_initialization(self, prosumer):
        """Initialisation of the time_series

        Parameters
        ----------
        prosumer : object of type prosumer
            Prosumer container


        """
        return super().time_series_initialization(prosumer)

    def time_series_finalization(self, prosumer):
        """Finalisation of the time series

        Parameters
        ----------
        prosumer : object of type prosumer
            Prosumer container


        """
        return self.res