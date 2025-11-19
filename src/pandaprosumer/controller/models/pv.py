import numpy as np
from pandaprosumer.controller.base import BasicProsumerController


class SenergyNetsPvProductionController(BasicProsumerController):
    """
    Controller for SenergyNets PV production.

    This controller represents a simple PV model that:

     - Reads static PV system parameters from the element data
     - Receives time-series inputs (irradiance, solar elevation, etc.) via the generic mapping into ``self.inputs``.
     - Applies constraints to the active power output `p_w` (in W):

        - Negative power is clamped to 0 W.
        - If the solar elevation is below the horizon
          (solar_elevation_deg < 0), power is set to 0 W.
        - Power is limited to the installed peak power
          ("peakpower [kW] * 1000").

      Writes the corrected power into ``self.step_results`` and into the controller's time-series
      result array via ``finalize()``

    The detailed PV production (e.g. from PVGIS / pvlib) is
    computed outside and provided as time series inputs, but this controller ensures
    that the resulting time series are only consistent with basic
    physical constraints and the installed system size.
    """

    @classmethod
    def name(cls):
        """Name of the PV Production time series

        """
        return "sn_pv_production"

    def __init__(
        self,
        prosumer,
        pv_production_object,
        order,
        level,
        data_source=None,
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
            data_source=data_source,
            in_service=in_service,
            index=index,
            **kwargs,
        )


        self.applied = False
        self._idx_p_w = self._safe_input_index("p_w")
        self._idx_solar_elev = self._safe_input_index("solar_elevation_deg")

        # Peak power [kW] from the element table (sn_pv_production).
        self._peakpower_kw = self._read_peakpower_from_element()

#added new helper functions
    def _safe_input_index(self, col_name):
        """
        Return the index of a given column in ``self.input_columns``.

        Parameters
        ----------
        col_name : str
            Name of the column to look up.

        Returns
        -------
        int
            Column index in ``self.input_columns``.

        """
        try:
            return self.input_columns.index(col_name)
        except ValueError as exc:
            raise ValueError(
                f"Column '{col_name}' not found in input_columns of "
                f"{self.__class__.__name__}: {self.input_columns}"
            ) from exc

    def _read_peakpower_from_element(self):
        """
        Read the installed peak power (kW) from the associated
        ``sn_pv_production`` element.

        Returns
        -------
        float
            Peak power in kW.

        """
        elem = self.element_instance

        if hasattr(elem, "ndim") and elem.ndim == 2:
            peak_col = "peakpower"
            if peak_col in elem.columns:
                return float(elem[peak_col].iloc[0])
            return 0.0
        else:
            try:
                return float(elem["peakpower"])
            except Exception:
                return 0.0


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
        self.applied = False

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
        """
        Main control logic for the PV controller.

        -Start from the time-series inputs in ``self.inputs`` which are
           via ``GenericMapping`` (irradiance, solar elevation,
           etc., and possibly a raw ``p_w``).
        -For each controlled PV element:
           * Read the power ``p_w`` [W].
           * Apply basic physical constraints:
             - If ``solar_elevation_deg < 0`` → ``p_w := 0``.
             - If ``p_w < 0`` → ``p_w := 0``.
             - If ``p_w > peakpower_kw * 1000`` → clip to that value.
        -Store the corrected values as the controller's results via
           ``self.finalize()``.

        Parameters
        ----------
        prosumer : object
            Prosumer container.
        """
        super().control_step(prosumer)

        result = self.inputs.copy()
        nb_elements = result.shape[0]

        for e in range(nb_elements):
            p_w = result[e, self._idx_p_w]  # [W]
            solar_el = result[e, self._idx_solar_elev]  # [deg]

            # Apply physical constraints

            # Sun below horizon: no PV production
            if solar_el < 0.0:
                p_w = 0.0

            if p_w < 0.0:
                p_w = 0.0

            # limit to installed peak power if available
            if self._peakpower_kw > 0.0:
                p_max_w = self._peakpower_kw * 1000.0  # kW -> W
                if p_w > p_max_w:
                    p_w = p_max_w

            result[e, self._idx_p_w] = p_w

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
