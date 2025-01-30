"""
Module containing the StratifiedHeatStorageController class.
"""

import numpy as np
import pandas as pd
from functools import partial
import matplotlib.pyplot as plt
from numba import njit

from pandaprosumer.controller.base import BasicProsumerController
from pandaprosumer.constants import CELSIUS_TO_K, TEMPERATURE_CONVERGENCE_THRESHOLD_C
from pandaprosumer.mapping import FluidMixMapping


@njit
def _update_layers_temps(layer_temps_c,
                         mdot_charge_kg_per_s,
                         t_charge_c,
                         mdot_discharge_kg_per_s,
                         t_return_c,
                         t_ext_c,
                         cp_j_per_kgk,
                         rho_kg_per_m3,
                         A_m2,
                         dz_m,
                         Sl_m2,
                         S1_m2,
                         SN_m2,
                         k_star_w_per_mk,
                         U_w_per_m2k,
                         U1_w_per_m2k,
                         UN_w_per_m2k,
                         resol,
                         layer_charge_in=None,
                         layer_charge_out=0,
                         layer_discharge_out=None,
                         layer_discharge_in=0):
    """
    Compute the new temperature for every layer in the tank
    when applying a charge and discharge to the heat storage.
    The calculation is based on physical equation considering heat losses to the environment,
    heat diffusion in the storage, and the convection due to the charging and/or discharging flow,
    calculating the temperature variation in K/s for each layer layer_index.

    Use numba 'just in time' compilation for faster calculation.

    :param mdot_charge_kg_per_s: Charging Mass flow [kg/s]
    :param t_charge_c: Charge temperature, applied at the top of the storage when charging [°C]
    :param mdot_discharge_kg_per_s: Discharging Mass flow [kg/s]
    :param t_return_c: Return temperature, applied at the bottom of the storage when discharging [°C]

    :return layer_temps_c: The new temperatures list [°C]
    """
    
    layers_number = len(layer_temps_c)

    if layer_charge_in is None:
        layer_charge_in = layers_number - 1
    if layer_discharge_out is None:
        layer_discharge_out = layers_number - 1

    # dt_max_s = dz_m / (abs(mdot_charge_kg_per_s - mdot_discharge_kg_per_s) / (rho_kg_per_m3 * A_m2)) / 2
    dt_max_s = 1

    offset = 1 if resol // dt_max_s != resol / dt_max_s else 0
    nb_intervals = int(resol // dt_max_s + offset)
    dt_s = resol / nb_intervals

    # Repeat the calculation so the timestep is not too big
    for i in range(nb_intervals):
        # Calculate the new temperature for every layer in the tank
        new_layer_temps_c = layer_temps_c.copy()
        for layer_index in range(layers_number):
            T_1 = layer_temps_c[0]
            T_2 = layer_temps_c[1]
            T_N = layer_temps_c[-1]
            T_N_minus_1 = layer_temps_c[-2]

            # Check if the current layer is between the charging and the extraction points
            if layer_index == layer_charge_in:
                convection_charge_w = mdot_charge_kg_per_s * cp_j_per_kgk * (t_charge_c - layer_temps_c[layer_index])
            elif layer_index in range(layer_charge_out, layer_charge_in):
                convection_charge_w = mdot_charge_kg_per_s * cp_j_per_kgk * (layer_temps_c[layer_index + 1] - layer_temps_c[layer_index])
            else:
                convection_charge_w = 0

            # Check if the current layer is between the discharging and the return points
            if layer_index == layer_discharge_in:
                convection_discharge_w = mdot_discharge_kg_per_s * cp_j_per_kgk * (t_return_c - layer_temps_c[layer_index])
            elif layer_index in range(layer_discharge_in + 1, layer_discharge_out + 1):
                convection_discharge_w = mdot_discharge_kg_per_s * cp_j_per_kgk * (layer_temps_c[layer_index - 1] - layer_temps_c[layer_index])
            else:
                convection_discharge_w = 0

            # Heat losses and diffusion applied to every layer in the tank
            if layer_index == 0:  # bottom layer
                # see equation (3) in the paper
                heat_losses_w = U1_w_per_m2k * S1_m2 * (t_ext_c - T_1)
                diffusion_w = (4 / 3) * ((k_star_w_per_mk * A_m2) / dz_m) * (T_2 - T_1)
            elif layer_index < layers_number - 1:  # intermediate layer
                # see equations (4) in the paper
                heat_losses_w = U_w_per_m2k * Sl_m2 * (t_ext_c - layer_temps_c[layer_index])
                t_sec_order_diffusion_c = layer_temps_c[layer_index - 1] - 2*layer_temps_c[layer_index] + layer_temps_c[layer_index + 1]
                diffusion_w = ((k_star_w_per_mk * A_m2) / dz_m) * t_sec_order_diffusion_c
            else:  # top layer
                # see equation (5) in the paper
                heat_losses_w = UN_w_per_m2k * SN_m2 * (t_ext_c - T_N)
                diffusion_w = (4 / 3) * ((k_star_w_per_mk * A_m2) / dz_m) * (T_N_minus_1 - T_N)

            numerator_w = heat_losses_w + diffusion_w + convection_charge_w + convection_discharge_w
            denominator_ws_per_k = rho_kg_per_m3 * cp_j_per_kgk * A_m2 * dz_m

            delta_layer_temp_k_per_s = numerator_w / denominator_ws_per_k
            new_layer_temps_c[layer_index] += delta_layer_temp_k_per_s * dt_s
        layer_temps_c = new_layer_temps_c

    return layer_temps_c


class StratifiedHeatStorageController(BasicProsumerController):
    """
    Controller for stratified heat storage systems.

    The stratified heat storage is implemented from *Untrau et al., A fast and accurate 1-dimensional model for dynamic
    simulation and optimization of a stratified thermal energy storage, 2023*

    Model a stratified thermal energy storage, which uses one single tank that is charged from the top with hot fluid
    while the cold fluid returning to the storage is charged from the bottom. The model assumes a vertical
    discretization of the tank with layers of uniform temperatures

    When charging with the mapped feed temperature and mass flow, the return temperature is the one on the bottom
    layer of the storage.
    When discharging with the return temperature and mass flow required by the downstream elements, the discharge
    temperature is the one on top of the storage.

    Note that the time step should not be too long compared to the volume of a layer and the (dis)charging mass flow
    so that less than the volume of a layer will be displaced in a time step.

    :param prosumer: The prosumer object
    :param stratified_heat_storage_object: The stratified heat storage object
    :param order: The order of the controller
    :param level: The level of the controller
    :param init_soc: Initial state of charge
    :param in_service: The in-service status of the controller
    :param index: The index of the controller
    :param kwargs: Additional keyword arguments
    """

    @classmethod
    def name(cls):
        return "stratified_heat_storage"

    def __init__(self, prosumer, stratified_heat_storage_object, order, level, init_layer_temps_c=None, plot=False,
                 in_service=True, index=None, name=None, **kwargs):
        """
        Constructor method
        """
        super().__init__(prosumer, stratified_heat_storage_object, order=order, level=level, in_service=in_service,
                         index=index, name=name, **kwargs)

        # Not in the paper nomenclature, is the number of layers
        self.N_l = int(self._get_element_param(prosumer, 'n_layers'))
        t_ext_c = self._get_element_param(prosumer, 't_ext_c')

        if init_layer_temps_c is None:
            self._layer_temps_c = [t_ext_c] * self.N_l
        elif not np.iterable(init_layer_temps_c):
            self._layer_temps_c = [init_layer_temps_c] * self.N_l
        else:
            self._layer_temps_c = init_layer_temps_c

        self.fluid = prosumer.fluid
        # TODO: use thermal conductivity of prosumer.fluid
        k_w_per_mk = self._get_element_param(prosumer, 'k_fluid_w_per_mk')  # 0.598  # water

        self.H_m = self._get_element_param(prosumer, 'tank_height_m')
        r_int_m = self._get_element_param(prosumer, 'tank_internal_radius_m')
        d_insu_m = self._get_element_param(prosumer, 'insulation_thickness_m')
        r_ext_m = self._get_element_param(prosumer, 'tank_external_radius_m')
        self.A_m2 = np.pi * r_int_m ** 2
        perimeter_m = np.pi * r_int_m * 2

        k_insu_w_per_mk = self._get_element_param(prosumer, 'k_insu_w_per_mk')  # 45  # steel
        k_wall_w_per_mk = self._get_element_param(prosumer, 'k_wall_w_per_mk')
        self.k_star_w_per_mk = k_w_per_mk + k_wall_w_per_mk * ((r_ext_m ** 2 - r_int_m ** 2) / r_int_m ** 2)
        h_ext_w_per_m2k = self._get_element_param(prosumer, 'h_ext_w_per_m2k')  # natural convection

        # Heat transfer coefficient with the environment (diffusion through insulation + convection with ambient air)
        self.U_w_per_m2k = 1 / ((1 / h_ext_w_per_m2k) + (d_insu_m / k_insu_w_per_mk))  # see eq. 6
        # We assume that the tank fluid to overall heat transfer coefficient for the top and bottom layers is the same
        # as the overall heat transfer coefficient
        self.U1_w_per_m2k = self.UN_w_per_m2k = self.U_w_per_m2k

        self.dz_m = self.H_m / self.N_l  # 𝛥z (layer high)

        # Heat exchange areas
        self.SN_m2 = perimeter_m * self.dz_m
        self.S1_m2 = self.Sl_m2 = self.A_m2 + self.SN_m2

        # initial temperatures are stored for computing stored energy (see eq. 8 in the paper)
        self.init_layer_temps_c = self._layer_temps_c.copy()

        self.t_previous_out_charge_c = np.nan
        self.t_previous_in_charge_c = np.nan
        self.mdot_previous_in_kg_per_s = np.nan

        # Used for debugging
        self.debug = plot
        if self.debug:
            self._layer_temps_tab_c = []
            self.t_charge_tab_c = []
            self.t_discharge_tab_c = []
            self.mdot_charge_tab_kg_per_s = []
            self.mdot_discharge_tab_kg_per_s = []

    @property
    def _t_received_in_c(self):
        if not np.isnan(self.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY]):
            return self.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY]
        else:
            return np.nan

    @property
    def _mdot_received_kg_per_s(self):
        if not np.isnan(self.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY]):
            return self.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY]
        else:
            return np.nan

    def _t_m_to_receive_init(self, prosumer):
        """
        Return the expected received Feed temperature, return temperature and mass flow in °C and kg/s

        :param prosumer: The prosumer object
        :return: A Tuple (Feed temperature, return temperature and mass flow)
        """
        t_demand_out_c, t_demand_in_c, mdot_demand_tab_required_kg_per_s = self.t_m_to_deliver(prosumer)
        mdot_demand_kg_per_s = np.sum(mdot_demand_tab_required_kg_per_s)
        t_charge_in_c = self._get_element_param(prosumer, 'min_useful_temp_c')  # self._layer_temps_c[-1]
        # If the required feed downstream temperature is null, it means that there is no downstream mapped controller
        # so ask treturn_required_c charge the storage at the min_useful_temp_c (or current top layer temperature ?)
        if t_demand_out_c < 1e-6 or mdot_demand_kg_per_s < 1e-6:
            t_required_in_c = t_charge_in_c
        else:
            t_required_in_c = t_demand_out_c

        # TODO: Is the return temp the bottom layer temp or the responders' t_return ?
        t_charge_out_c = self._t_charge_out

        # If the storage is full -> do not required heat from upstream for charging
        if mdot_demand_kg_per_s > 0 and self._get_max_stored_energy_kwh(t_charge_in_c, t_required_in_c) - self._get_stored_energy_kwh(t_charge_in_c) < 1:
            # FixMe: Go here if min_useful_temp_c = t_charge_in_c > t_required_in_c = t_demand_out_c
            return t_demand_out_c, t_demand_in_c, mdot_demand_kg_per_s

        # For charging, Ask to receive a mass flow corresponding to the volume of all layers in the storage for which
        # the temperature is smaller than the feed temperature
        rho_mean_kg_per_m3 = self.fluid.get_density(CELSIUS_TO_K + np.mean(self._layer_temps_c))
        m_layer_kg = self.A_m2 * self.dz_m * rho_mean_kg_per_m3
        nb_cold_layers = np.sum(np.array(self._layer_temps_c) < t_required_in_c)
        mdot_charge_kg_per_s = nb_cold_layers * m_layer_kg / self.resol

        mdot_required_kg_per_s = mdot_demand_kg_per_s + mdot_charge_kg_per_s
        t_required_out_c = (mdot_demand_kg_per_s * t_demand_in_c + mdot_charge_kg_per_s * t_charge_out_c) / mdot_required_kg_per_s

        if not np.isnan(self.t_previous_out_charge_c):
            mdot_charge_kg_per_s = mdot_demand_kg_per_s * (t_demand_in_c - t_required_out_c) / (t_required_out_c - t_charge_out_c)
            return self.t_previous_in_charge_c, self.t_previous_out_charge_c, mdot_charge_kg_per_s

        return t_required_in_c, t_required_out_c, mdot_required_kg_per_s

    @property
    def _t_charge_out(self):
        """
        Temperature of the fluid returned to the initiator in °C
        """
        return self._layer_temps_c[0]

    def _get_max_stored_energy_kwh(self, extraction_temp_c, t_charge_c):
        """
        Maximal storable energy E if charging at the temperature temp_charge_c.
        Calculated by comparing a case with uniform temperature to the initial state. See equation (8) in the paper

        :param extraction_temp_c: Useful Extraction temperature (only energy above this level is considered) (°C)
        :param t_charge_c: Temperature charge (°C)
        :return: Maximum storable energy E (kWh)
        """
        # 3.6e6 is the conversion factor from J to kWh
        ret = sum([float(self.fluid.get_density(CELSIUS_TO_K + t_charge_c)) * self.A_m2 *
                   float(self.fluid.get_heat_capacity(CELSIUS_TO_K + t_charge_c)) *
                   (t_charge_c - self.init_layer_temps_c[z]) * self.dz_m
                   for z in range(self.N_l) if t_charge_c >= extraction_temp_c - .1]) / 3.6e6
        return ret

    def _get_stored_energy_kwh(self, t_extraction_c):
        """
        Stored energy E(t) at any time
        Calculated by comparing current temperatures to the initial state. See equation (8) in the paper

        :param t_extraction_c: Useful Extraction temperature (only energy above this level is considered) (°C)
        :type t_extraction_c: float
        :return: Stored energy E(t) compared to initial state (kWh)
        """
        # 3.6e6 is the conversion factor from J to kWh
        ret = sum([float(self.fluid.get_density(CELSIUS_TO_K + self._layer_temps_c[z])) * self.A_m2 *
                   float(self.fluid.get_heat_capacity(CELSIUS_TO_K + self._layer_temps_c[z])) *
                   (self._layer_temps_c[z] - self.init_layer_temps_c[z]) * self.dz_m
                   for z in range(self.N_l) if self._layer_temps_c[z] >= t_extraction_c - .1]) / 3.6e6
        return ret

    def _calculate_heat_storage(self, prosumer, mdot_demand_kg_per_s, t_received_in_c, t_demand_out_c, t_demand_in_c,
                                t_discharge_out_c, mdot_received_kg_per_s, t_charge_out_c):
        # mass flow to provide at self._t_charge_c to provide the same energy to the demand
        # if abs(t_received_in_c - t_demand_out_c) < 1e-3:
        #     mdot_toprovide_kg_per_s = 0
        # else:
        if t_received_in_c - t_demand_out_c > 0:
            delta_t_demand_c = t_demand_out_c - t_demand_in_c
            mdot_toprovide_kg_per_s = mdot_demand_kg_per_s * delta_t_demand_c / (t_received_in_c - t_demand_out_c)
        else:
            mdot_toprovide_kg_per_s = mdot_demand_kg_per_s
        # if not self.debug:
        if mdot_toprovide_kg_per_s > mdot_received_kg_per_s:
            # If this energy cannot be provided, no charging but discharge
            mdot_bypass_kg_per_s = mdot_received_kg_per_s
            t_bypass_in_c = t_received_in_c
            mdot_charge_kg_per_s = 0
            # mdot_discharge_kg_per_s = sum(mdot_demand_tab_kg_per_s) - mdot_bypass_kg_per_s
            # If the required output temperature is between the feed and top layer temperature, calculate the
            # discharge mass flow to get this required temperature
            if abs(t_demand_out_c - t_discharge_out_c) > 1e-3:
                mdot_discharge_kg_per_s = mdot_bypass_kg_per_s * (t_received_in_c - t_demand_out_c) / (t_demand_out_c - t_discharge_out_c)
            else:
                mdot_discharge_kg_per_s = mdot_demand_kg_per_s - mdot_bypass_kg_per_s
            if mdot_discharge_kg_per_s < 0:
                # else, calculate the discharge mass flow to get the same energy
                # (considering that the return temperature would be the same)
                e_demand = mdot_demand_kg_per_s * (t_demand_out_c - t_demand_in_c)
                e_bypass = mdot_bypass_kg_per_s * (t_received_in_c - t_demand_out_c)
                mdot_discharge_kg_per_s = (e_demand - e_bypass) / (t_discharge_out_c - t_demand_in_c)
        else:
            # If this energy can be provided, charging with the extra mass flow
            mdot_bypass_kg_per_s = mdot_toprovide_kg_per_s
            mdot_charge_kg_per_s = mdot_received_kg_per_s - mdot_bypass_kg_per_s
            mdot_discharge_kg_per_s = 0
            t_bypass_in_c = t_received_in_c

        #     for i, m in enumerate(mdot_demand_tab_kg_per_s):
        #         if (t_discharge_c - t_return_demand_c) > 0:
        #             # Compensate the value of mass flow to provide the same energy
        #             # Because the discharge temperature is the one on the extraction layer
        #             # which can be different from the required feed temperature
        #             # FixMe: Take into account the temperature that will go through the storage from the production
        #             mdot_demand_tab_kg_per_s[i] = m * (t_feed_demand_c - t_return_demand_c) / (t_discharge_c - t_return_demand_c)
        #         else:
        #             # If the temperature in the storage is lower than the return temperature, it cannot provide any power
        #             mdot_demand_tab_kg_per_s[i] = 0
        #
        # mdot_discharge_kg_per_s = np.sum(mdot_demand_tab_kg_per_s)

        height_charge_in_m = self._get_element_param(prosumer, 'height_charge_in_m')
        height_charge_out_m = self._get_element_param(prosumer, 'height_charge_out_m')
        height_discharge_out_m = self._get_element_param(prosumer, 'height_discharge_out_m')
        height_discharge_in_m = self._get_element_param(prosumer, 'height_discharge_in_m')
        layer_charge_in = height_charge_in_m / self.H_m * self.N_l if not np.isnan(height_charge_in_m) else None
        layer_charge_out = height_charge_out_m / self.H_m * self.N_l if not np.isnan(height_charge_out_m) else None
        layer_discharge_out = height_discharge_out_m / self.H_m * self.N_l if not np.isnan(
            height_discharge_out_m) else None
        layer_discharge_in = height_discharge_in_m / self.H_m * self.N_l if not np.isnan(
            height_discharge_in_m) else None

        cp_discharge_j_per_kgk = self.fluid.get_heat_capacity(CELSIUS_TO_K + np.mean(self._layer_temps_c))
        rho_kg_per_m3 = self.fluid.get_density(CELSIUS_TO_K + np.mean(self._layer_temps_c))
        t_ext_c = self._get_element_param(prosumer, 't_ext_c')

        self._layer_temps_c = _update_layers_temps(layer_temps_c=np.array(self._layer_temps_c),
                                                   mdot_charge_kg_per_s=mdot_charge_kg_per_s,
                                                   t_charge_c=t_received_in_c,
                                                   mdot_discharge_kg_per_s=mdot_discharge_kg_per_s,
                                                   t_return_c=t_demand_in_c,
                                                   t_ext_c=t_ext_c,
                                                   cp_j_per_kgk=cp_discharge_j_per_kgk,
                                                   rho_kg_per_m3=rho_kg_per_m3,
                                                   A_m2=self.A_m2,
                                                   dz_m=self.dz_m,
                                                   Sl_m2=self.Sl_m2,
                                                   S1_m2=self.S1_m2,
                                                   SN_m2=self.SN_m2,
                                                   k_star_w_per_mk=self.k_star_w_per_mk,
                                                   U_w_per_m2k=self.U_w_per_m2k,
                                                   U1_w_per_m2k=self.U1_w_per_m2k,
                                                   UN_w_per_m2k=self.UN_w_per_m2k,
                                                   resol=self.resol,
                                                   layer_charge_in=layer_charge_in,
                                                   layer_charge_out=layer_charge_out,
                                                   layer_discharge_out=layer_discharge_out,
                                                   layer_discharge_in=layer_discharge_in)

        cp_discharge_j_per_kgk = float(self.fluid.get_heat_capacity(CELSIUS_TO_K + (t_discharge_out_c + t_demand_in_c) / 2))
        q_discharge_kw = mdot_discharge_kg_per_s * cp_discharge_j_per_kgk * (t_discharge_out_c - t_demand_in_c) / 1e3

        min_useful_temp_c = self._get_element_param(prosumer, 'min_useful_temp_c')
        e_stored_kwh = self._get_stored_energy_kwh(min_useful_temp_c)

        cp_bypass_j_per_kgk = self.fluid.get_heat_capacity(CELSIUS_TO_K + (t_bypass_in_c + t_demand_in_c) / 2)
        q_bypass_kw = mdot_bypass_kg_per_s * cp_bypass_j_per_kgk * (t_bypass_in_c - t_demand_in_c) / 1e3
        q_delivered_kw = q_discharge_kw + q_bypass_kw

        mdot_delivered_kg_per_s = mdot_bypass_kg_per_s + mdot_discharge_kg_per_s

        if mdot_delivered_kg_per_s > 0:
            t_delivered_out_c = (t_bypass_in_c * mdot_bypass_kg_per_s + t_discharge_out_c * mdot_discharge_kg_per_s) / mdot_delivered_kg_per_s
        else:
            t_delivered_out_c = t_discharge_out_c

        if abs(mdot_charge_kg_per_s + mdot_bypass_kg_per_s) < 1e-3:
            t_received_out_c = self._t_received_in_c
        else:
            t_received_out_c = (mdot_charge_kg_per_s * t_charge_out_c + mdot_bypass_kg_per_s * t_demand_in_c) / (mdot_charge_kg_per_s + mdot_bypass_kg_per_s)

        return (q_delivered_kw, q_bypass_kw, q_discharge_kw, e_stored_kwh,
                mdot_received_kg_per_s, t_received_in_c, t_received_out_c,
                mdot_delivered_kg_per_s, t_demand_in_c, t_delivered_out_c,
                mdot_charge_kg_per_s, t_charge_out_c,
                mdot_discharge_kg_per_s, t_discharge_out_c)

    def control_step(self, prosumer):
        """
        Executes the control step for the controller.

        :param prosumer: The prosumer object
        """
        super().control_step(prosumer)
        if not self._are_initiators_converged(prosumer):
            # If some of the initiators are not converged, do not run the control step
            self._unapply_initiators(prosumer)
            self.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: np.nan,
                                              FluidMixMapping.MASS_FLOW_KEY: np.nan}
            return

        # The discharge temperature is the one on top of the storage
        # Note that the time step should not be too long compared to the volume of this top layer and the mass flow
        t_discharge_out_c = self._layer_temps_c[-1]

        # When discharging, the temperature of the fluid that will be added at the bottom of the storage is the
        # temperature returned by the downstream elements.
        # Simple average of the temperatures but will have to be weighted by the mass flows in the future
        t_demand_out_c, t_demand_in_c, mdot_demand_tab_kg_per_s = self.t_m_to_deliver(prosumer)
        mdot_demand_kg_per_s = sum(mdot_demand_tab_kg_per_s)

        assert mdot_demand_kg_per_s >= 0, f"SHS {self.name} mdot_demand_kg_per_s is negative ({mdot_demand_kg_per_s}) for timestep {self.time} in prosumer {prosumer.name}"
        assert t_demand_out_c >= t_demand_in_c, f"SHS {self.name} t_demand_out_c < t_demand_in_c is negative ({t_demand_out_c} < {t_demand_in_c}) for timestep {self.time} in prosumer {prosumer.name}"
        assert t_demand_in_c >= 0, f"SHS {self.name} t_demand_in_c is negative ({t_demand_in_c}) for timestep {self.time} in prosumer {prosumer.name}"

        layer_temp_init_c = self._layer_temps_c.copy()

        rerun = True
        while rerun:
            self._layer_temps_c = layer_temp_init_c.copy()

            (q_delivered_kw, q_bypass_kw, q_discharge_kw, e_stored_kwh,
             mdot_received_kg_per_s, t_received_in_c, t_received_out_c,
             mdot_delivered_kg_per_s, t_demand_in_c, t_delivered_out_c,
             mdot_charge_kg_per_s, t_charge_out_c,
             mdot_discharge_kg_per_s, t_discharge_out_c) = self._calculate_heat_storage(prosumer,
                                                                                        mdot_demand_kg_per_s,
                                                                                        self._t_received_in_c,
                                                                                        t_demand_out_c,
                                                                                        t_demand_in_c,
                                                                                        t_discharge_out_c,
                                                                                        self._mdot_received_kg_per_s,
                                                                                        self._t_charge_out)

            result_mdot_tab_kg_per_s = self._merit_order_mass_flow(prosumer,
                                                                   mdot_delivered_kg_per_s,
                                                                   mdot_demand_tab_kg_per_s)

            rerun = False
            if len(self._get_mapped_responders(prosumer)) > 1 and mdot_delivered_kg_per_s < mdot_demand_kg_per_s:
                # If the heat Pump is not able to deliver the required mass flow,
                # recalculate the condenser input temperature, considering that all the downstream elements will be
                # still return the same temperature, even if the mass flow delivered to them by the Heat Pump is lower
                t_return_tab_c = self.get_treturn_tab_c(prosumer)
                if abs(mdot_delivered_kg_per_s) > 1e-8:
                    t_return_demand_new_c = np.sum(result_mdot_tab_kg_per_s * t_return_tab_c) / mdot_delivered_kg_per_s
                else:
                    t_return_demand_new_c = t_demand_in_c
                if abs(t_return_demand_new_c - t_demand_in_c) > 1:
                    # If this recalculation changes the condenser input temperature, rerun the calculation
                    # with the new temperature
                    t_demand_in_c = t_return_demand_new_c
                    rerun = True

        # result = np.array([[mdot_discharge_kg_per_s,
        #                     t_discharge_out_c,
        #                     q_delivered_kw,
        #                     e_stored_kwh]])

        cp_received_j_per_kgk = self.fluid.get_heat_capacity(CELSIUS_TO_K + (t_received_in_c + t_received_out_c) / 2)
        q_received_kw = mdot_received_kg_per_s * cp_received_j_per_kgk * (t_received_in_c - t_received_out_c) / 1e3
        cp_charge_j_per_kgk = self.fluid.get_heat_capacity(CELSIUS_TO_K + (t_received_in_c + t_charge_out_c) / 2)
        q_charge_kw = mdot_charge_kg_per_s * cp_charge_j_per_kgk * (t_received_in_c - t_charge_out_c) / 1e3

        result = np.array([[q_received_kw, q_delivered_kw, q_charge_kw, q_discharge_kw, e_stored_kwh,
                            mdot_received_kg_per_s, t_received_in_c, t_received_out_c,
                            mdot_delivered_kg_per_s, t_demand_in_c, t_delivered_out_c,
                            mdot_charge_kg_per_s, t_charge_out_c,
                            mdot_discharge_kg_per_s, t_discharge_out_c]])

        result_fluid_mix = []
        for mdot_kg_per_s in result_mdot_tab_kg_per_s:
            result_fluid_mix.append({FluidMixMapping.TEMPERATURE_KEY: t_delivered_out_c,
                                     FluidMixMapping.MASS_FLOW_KEY: mdot_kg_per_s})

        # Used for debugging
        if self.debug:
            self._layer_temps_tab_c += [self._layer_temps_c]  # Store all the layers temps history for analysis
            self.t_charge_tab_c += [t_received_in_c]
            self.t_discharge_tab_c += [t_demand_in_c]
            self.mdot_charge_tab_kg_per_s += [mdot_charge_kg_per_s]
            self.mdot_discharge_tab_kg_per_s += [mdot_discharge_kg_per_s]

        assert q_received_kw >= 0, f"SHS {self.name} q_received_kw is negative ({q_received_kw}) for timestep {self.time} in prosumer {prosumer.name}"
        assert q_delivered_kw >= 0, f"SHS {self.name} q_delivered_kw is negative ({q_delivered_kw}) for timestep {self.time} in prosumer {prosumer.name}"
        assert q_charge_kw >= 0, f"SHS {self.name} q_charge_kw is negative ({q_charge_kw}) for timestep {self.time} in prosumer {prosumer.name}"
        assert q_discharge_kw >= 0, f"SHS {self.name} q_discharge_kw is negative ({q_discharge_kw}) for timestep {self.time} in prosumer {prosumer.name}"
        # assert e_stored_kwh >= 0, f"SHS {self.name} e_stored_kwh is negative ({e_stored_kwh}) for timestep {self.time} in prosumer {prosumer.name}"
        assert mdot_received_kg_per_s >= 0, f"SHS {self.name} mdot_received_kg_per_s is negative ({mdot_received_kg_per_s}) for timestep {self.time} in prosumer {prosumer.name}"
        assert mdot_delivered_kg_per_s >= 0, f"SHS {self.name} mdot_delivered_kg_per_s is negative ({mdot_delivered_kg_per_s}) for timestep {self.time} in prosumer {prosumer.name}"

        if np.isnan(self.t_keep_return_c) or mdot_received_kg_per_s == 0 or abs(t_received_out_c - self.t_keep_return_c) < TEMPERATURE_CONVERGENCE_THRESHOLD_C or len(self._get_mapped_initiators_on_same_level(prosumer)) == 0:
            # If the actual output temperature is the same as the promised one, the storage is correctly applied
            self.finalize(prosumer, result, result_fluid_mix)
            self.applied = True
            self.t_previous_out_charge_c = np.nan
            self.t_previous_in_charge_c = np.nan
            self.mdot_previous_in_kg_per_s = np.nan
        else:
            # Else, reapply the upstream controllers with the new temperature so no energy appears or disappears
            self._layer_temps_c = layer_temp_init_c
            self._unapply_initiators(prosumer)
            self.t_previous_out_charge_c = t_received_out_c
            self.t_previous_in_charge_c = t_received_in_c
            self.mdot_previous_in_kg_per_s = mdot_delivered_kg_per_s
            self.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: np.nan,
                                              FluidMixMapping.MASS_FLOW_KEY: np.nan}
