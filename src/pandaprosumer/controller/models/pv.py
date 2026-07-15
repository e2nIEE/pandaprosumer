from pandaprosumer.controller.base import BasicProsumerController


class PvProductionController(BasicProsumerController):
    """
    Controller for PV production.

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
        return "pv_production"

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
            Prosumer container
        pv_production_object : object of type PvProductionControllerData
            PV production controller data object, where PV production inputs are defined
        order : int
            The order of the controller within its level.
        level : int
            The level of the controller in the prosumer's controller stack.
        data_source : object, optional
            Optional data source (e.g. DataFrame) for PV time series
        in_service : bool, optional
            True for in_service or False for out of service, by default True
        index : int, optional
            Force a specified controller ID. If None, the next free index is selected.
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

        # Peak power [kW] from the element table (pv_production).
        self._peakpower_kw = self._read_peakpower_from_element()

    # Added new helper functions
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
        ``pv_production`` element.

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
            except (KeyError, ValueError, TypeError):
                return 0.0


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
