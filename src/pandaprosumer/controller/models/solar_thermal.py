import numpy as np
from pandaprosumer.controller.base import BasicProsumerController
from pandaprosumer.mapping.fluid_mix import FluidMixMapping
import math


def collector_initial_parameters(
        # a_c,
        a_0,
        a_1,
        a_2,
        m_test,
        cp_test,
):
    """It calculates the 3 parameters that characterize the thermodynamic
    performance of the solar collector

    Parameters
    ----------
    a_c : float
        collector area [m_2]
    a_0 : float
        collector curve optical efficiency [-]
    a_1 : float
        collector curve first order efficiency [W_per_m_2_K]
    a_2 : float
        collector curve second order efficiency [W_per_m_2_K_2]
    m_test : float
        collector test specific flow rate [kg_per_h_m]
    cp_test : float
       heat capacity of the collector test fluid [kJ_per_kg_K]

    Returns
    -------
    list
        3 parameters of the solar collector
    """
    # fr_tau_alpha_n = a_0 * (1 + 3.6 * a_c * a_1 / (2 * m_test * cp_test))**(-1)
    fr_tau_alpha_n = a_0 * (1 + 3.6 * a_1 / (2 * m_test * cp_test)) ** (-1)
    # fr_ul = a_1 * (1 + 3.6 * a_c * a_1 / (2 * m_test * cp_test))**(-1)
    fr_ul = a_1 * (1 + 3.6 * a_1 / (2 * m_test * cp_test)) ** (-1)
    # fr_ul_t = a_2 * (1 + 3.6 * a_c * a_1 / (2 * m_test * cp_test))**(-1)
    fr_ul_t = a_2 * (1 + 3.6 * a_1 / (2 * m_test * cp_test)) ** (-1)
    return [fr_tau_alpha_n, fr_ul, fr_ul_t]


def capacitance_correction_factor(
        m,
        a_c,
        n_c,
        cp,
        fr_ul,
):
    """It calculates the factor that considers both the effect of
    the different fluid and flow rate between collector test and operation

     Parameters
     ----------
     m : float
         the specific collector flowrate under current conditions [kg_per_h]
     a_c : float
        collector area [m_2]
     n_c : float
        number of collectors [-]
     cp : float
       heat capacity of the fluid used [kJ_per_kg_K]
     fr_ul : float
        parameter of the solar collector [W_per_m_2_K]

     Returns
     -------
     float
         capacitance correction factor [-]
    """
    if m > 0:
        f_finul = -m * cp / (3.6 * a_c) * math.log(1 - 3.6 * fr_ul * a_c / (m * cp))
        r = (m * cp / (n_c * a_c)) * (1 - math.exp(-3.6 * n_c * a_c * f_finul / (m * cp))) / (3.6 * fr_ul)
    else:
        r = 1
    return r


def series_connection_correction_factor(
        m,
        a_c,
        n_c,
        cp,
        n_series,
        fr_ul,
):
    """It calculates the factor that considers  the effect of
    connecting n number of collectors in series

    Parameters
    ----------
    m : float
         the specific collector flow rate under current conditions [kg_per_h]
    a_c : float
        collector area [m_2]
    n_c : float
        number of collectors [-]
    cp : float
       heat capacity of the fluid used [kJ_per_kg_K]
    n_series : int
        number of collectors connected in series [-]
    fr_ul : float
        parameter of the solar collector [W_per_m_2_K]

    Returns
    -------
    float
         series connection correction factor [-]
    """
    if m > 0:
        k = 3.6 * n_c * a_c * fr_ul / (m * cp)
        r = (1 - (1 - k) ** n_series) / (n_series * k)
    else:
        r = 1
    return r


def piping_correction_factor(
        m,
        a_c,
        cp,
        l_pipe,
        d_pipe,
        t_ins,
        k_ins,
        fr_ul,
):
    """It calculates the factor that considers  the
     thermal losses from the connecting pipes

    Parameters
    ----------
    m : float
         the specific collector flow rate under current conditions [kg_per_h]
    a_c : float
        collector area [m_2]
    cp : float
       heat capacity of the fluid used [kJ_per_kg_K]
    l_pipe : float
        solar field piping length [m]
    d_pipe : float
        piping diameter [m]
    t_ins : float
        piping insulation thickness [m]
    k_ins : float
        piping insulation conductivity [W_per_m_K]
    fr_ul : float
        parameter of the solar collector [W_per_m_2_K]

    Returns
    -------
     list
         piping correction factor [-]
    """
    if m > 0:
        up = 2 * k_ins / ((d_pipe + 2 * t_ins) * math.log(1 + 2 * t_ins / d_pipe))
        uap = up * l_pipe * (d_pipe + 2 * t_ins)
        r_0 = (1 / (1 + 3.6 * uap / (m * cp)))
        r_1 = ((1 - 3.6 * uap / (m * cp) + 2 * uap / (a_c * fr_ul)) / (1 + 3.6 * uap / (m * cp)))
        r_2 = r_1
    else:
        r_0 = 1
        r_1 = 1
        r_2 = 1
    return [r_0, r_1, r_2]


def radiation_incidence_iam_effect(
        I_beam,
        I_diff,
        I_gr,
        theta,
        k_t_alpha_50,
        slope
):
    """It calculates the radiation incidence on the collector
    taking into account the Incidence Angle Modifier effect

    Parameters
    ----------
    I_beam : float
        beam solar radiation [w_per_m2]
    I_diff : float
        diffuse solar radiation [w_per_m2]
    I_gr : float
        ground reflected radiation [w_per_m2]
    theta : float
        radiation incidence angle [deg]
    k_t_alpha_50 : float
        incident angle modifier at theta 50 deg [-]
    slope : float
        collector slope [deg]

    Returns
    -------
    float
        radiation incidence on the collector
        accounting for the Incidence Angle Modifier effect [w_per_m2]
    """
    b_0 = (1 - k_t_alpha_50) / (1 - math.cos(math.radians(50)) - 1)
    theta_diff = 59.7 - 0.1388 * slope + 0.001497 * slope ** 2
    theta_gr = 90 - 0.5788 * slope + 0.002693 * slope ** 2

    k_t_alpha = 1 - b_0 * (1 / math.cos(math.radians(theta)) - 1)
    k_t_alpha_diff = 1 - b_0 * (1 / math.cos(math.radians(theta_diff)) - 1)
    k_t_alpha_gr = 1 - b_0 * (1 / math.cos(math.radians(theta_gr)) - 1)

    gt = k_t_alpha * I_beam + k_t_alpha_diff * I_diff + k_t_alpha_gr * I_gr
    return gt


class SolarThermalController(BasicProsumerController):
    """Definition of the Class for the Controller

    Parameters
    ----------
    BasicProsumerController : _type_
        _description_

    Returns
    -------
    _type_
        _description_
    """

    @classmethod
    def name(cls):
        """Name of the solar thermal component"""
        return "solar_thermal"

    def __init__(
            self,
            prosumer,
            solar_themal_object,
            # data_source,
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
            Prosumer container
        solar_themal_object : _object of type SenergyNetsSolarThermalController
            Solar Thermal object, where solar thermal inputs are defined
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
        super().__init__(
            prosumer,
            solar_themal_object,
            order=order,
            level=level,
            in_service=in_service,
            index=index,
            **kwargs,
        )

        # self.ds = data_source
        self.element = self.obj.element
        self.element_variable = (
            self.obj.element_variable if hasattr(self.obj, "element_variable") else None
        )
        self.element_index = self.obj.element_index
        self.pros = prosumer[self.element].loc[self.element_index, :]
        # self.res = np.zeros(
        #     [len(self.element_index), len(self.dur), len(self.result_columns)]
        # )
        self.res = np.zeros(
            [len(self.element_index), len(self.time_index), len(self.result_columns)]
        )

        # all this stuff used to be initialized in .time_step() in pandaprosumer/controller/sector_coupling/plant.py -- isthis valid?
        self.res_step = None
        self.time = None
        self.applied = None

        # time series
        # self.pn_beam_solar_radiation = self._get_element_param(prosumer, "beam_solar_radiation_w_m2")
        # self.pn_diffuse_solar_radiation = self._get_input("diffuse_solar_radiation_w_m2")
        # self.pn_ground_solar_radiation = self._get_input("ground_solar_radiation_w_m2")
        # self.pn_radiation_incidence_angle = self._get_input("radiation_incidence_angle_deg")
        # self.pn_ambient_temperature = self._get_input("ambient_temperature_C")
        # self.pn_inlet_mass_flow_rate = self._get_input("inlet_mass_flow_rate_kg_h")
        # self.pn_inlet_temperature = self._get_input("inlet_temperature_C")

    def time_step(self, prosumer, time):
        """It is the first call in each time step, thus suited for things like
        reading profiles or prepare the controller for the next control step.

        .. note:: This method is ONLY being called during time-series simulation!

        :param prosumer:
        :param time:


        """
        super().time_step(prosumer, time)
        self.res_step = np.zeros(
            [len(self.element_index), len(self.obj.result_columns)]
        )
        self.time = time
        self.applied = False
        # self._beam_solar_radiation = self.ds.get_time_step_value(time, self.pn_beam_solar_radiation)
        # self._diffuse_solar_radiation = self.ds.get_time_step_value(time, self.pn_diffuse_solar_radiation)
        # self._ground_solar_radiation = self.ds.get_time_step_value(time, self.pn_ground_solar_radiation)
        # self._radiation_incidence_angle = self.ds.get_time_step_value(time, self.pn_radiation_incidence_angle)
        # self._ambient_temperature = self.ds.get_time_step_value(time, self.pn_ambient_temperature)
        # self._inlet_mass_flow_rate = self.ds.get_time_step_value(time, self.pn_inlet_mass_flow_rate)
        # self._inlet_temperature = self.ds.get_time_step_value(time, self.pn_inlet_temperature)


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
        """It implements the thermodynamic model of the solar thermal component

        Parameters
        ----------
        prosumer : _type_
            _description_
        """

        m = self._get_input("inlet_mass_flow_rate_kg_h") / self.pros.number_collectors[0]  # /self.pros.series[0]

        fr_tau_alpha_n, fr_ul, fr_ul_t = collector_initial_parameters(
            # self.pros.collector_area[0],
            self.pros.optical_efficiency[0],
            self.pros.thermal_losses[0],
            self.pros.second_thermal_losses[0],
            self.pros.flow_rate[0],
            self.pros.test_specific_heat[0],
        )

        r_capacitance = capacitance_correction_factor(
            self._get_input("inlet_mass_flow_rate_kg_h"),
            self.pros.collector_area[0],
            self.pros.number_collectors[0],
            self.pros.use_specific_heat[0],
            fr_ul
        )

        fr_tau_alpha_n = r_capacitance * fr_tau_alpha_n
        fr_ul = r_capacitance * fr_ul
        fr_ul_t = r_capacitance * fr_ul_t
        # print(r_capacitance)

        r_series = series_connection_correction_factor(
            m,
            self.pros.collector_area[0],
            self.pros.number_collectors[0],
            self.pros.use_specific_heat[0],
            self.pros.series[0],
            fr_ul
        )

        fr_tau_alpha_n = r_series * fr_tau_alpha_n
        fr_ul = r_series * fr_ul
        fr_ul_t = r_series * fr_ul_t

        # print(r_series)

        r_piping = piping_correction_factor(
            m,
            self.pros.collector_area[0],
            self.pros.use_specific_heat[0],
            self.pros.piping_length[0],
            self.pros.piping_diameter[0],
            self.pros.piping_thickness[0],
            self.pros.piping_conductivity[0],
            fr_ul
        )
        fr_tau_alpha_n = r_piping[0] * fr_tau_alpha_n
        fr_ul = r_piping[1] * fr_ul
        fr_ul_t = r_piping[2] * fr_ul_t

        # print(r_piping)

        gt = radiation_incidence_iam_effect(
            self._get_input("beam_solar_radiation_w_m2"),
            self._get_input("diffuse_solar_radiation_w_m2"),
            self._get_input("ground_solar_radiation_w_m2"),
            self._get_input("radiation_incidence_angle_deg"),
            self.pros.incidence_angle[0],
            self.pros.collector_slope[0]
        )
        # print(f"gt: {gt}")
        # fr_ul_t = 0.02
        a_field = self.pros.collector_area[0] * self.pros.number_collectors[0]
        aa = fr_ul_t * a_field
        bb = -2 * fr_ul_t * self._get_input("ambient_temperature_C") * a_field + fr_ul * a_field + 2 * self._get_input("inlet_mass_flow_rate_kg_h") * \
             self.pros.use_specific_heat[0] / 3.6
        cc = fr_ul_t * self._get_input("ambient_temperature_C") ** 2 * a_field - fr_ul * a_field * self._get_input("ambient_temperature_C") - fr_tau_alpha_n * gt * a_field - 2 * self._get_input("inlet_mass_flow_rate_kg_h") * \
             self.pros.use_specific_heat[0] * self._get_input("inlet_temperature_C") / 3.6
        if aa == 0:
            t_m = -bb / cc
        else:
            t_m = (-bb + math.sqrt(bb ** 2 - 4 * aa * cc)) / (2 * aa)
        # print(aa)
        # print(bb)
        # print(cc)
        # print(t_m)
        # print(fr_ul_t)
        # print(fr_ul)

        # Outputs
        outlet_flow_rate_kg_h = self._get_input("inlet_mass_flow_rate_kg_h")
        energy_gain_W = 2 * self._get_input("inlet_mass_flow_rate_kg_h") * self.pros.use_specific_heat[0] * (
                    t_m - self._get_input("inlet_temperature_C")) / 3.6
        if energy_gain_W == 0:
            outlet_temperature_C = self._get_input("inlet_temperature_C")
        elif energy_gain_W < 0:
            outlet_temperature_C = 2 * t_m - self._get_input("inlet_temperature_C")
        else:
            outlet_temperature_C = self._get_input("inlet_temperature_C") + 3.6 * energy_gain_W / (
                        self._get_input("inlet_mass_flow_rate_kg_h") * self.pros.use_specific_heat[0])

        outlet_flow_rate_kg_s = outlet_flow_rate_kg_h / 3600

        result_fluid_mix = []
        result_fluid_mix.append({FluidMixMapping.TEMPERATURE_KEY: outlet_temperature_C,
                                 FluidMixMapping.MASS_FLOW_KEY: outlet_flow_rate_kg_s})

        # considering other components to be connected to the cooler, please consider only the necessary outputs for your use case in Cordoba
        result = np.array([[
            outlet_temperature_C,
            outlet_flow_rate_kg_h,
            energy_gain_W]]
        )

        self.finalize(prosumer, result, result_fluid_mix)

        # idx = np.where(self.dur == self.time)[0][0]
        # array = np.stack([series for series in result], axis=1)
        # self.res[:, idx, :] = array

        # for j, mapping in enumerate(zip(self.element_index, self.obj.assigned_object)):
        #     print(self.obj.assigned_object)
        #     el_idx, ass_obj = mapping
        #     ass_obj.control_strategy(
        #         prosumer=prosumer, obj=self.obj, assigned_obj=ass_obj
        # )

        # set the "convergence condition" to tell the system that this controller is finished
        self.applied = True

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