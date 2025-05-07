import logging

import numpy as np
import pandas as pd
from pandapipes import Fluid, create_fluid_from_lib

from pandapower.create import _get_index_with_check, _set_entries, _add_to_entries_if_not_nan
from pandaprosumer.element import *
from pandapower.create import _get_index_with_check, _set_entries
from pandaprosumer.element import HeatPumpElementData, HeatDemandElementData, \
     HeatStorageElementData, IceChpElementData, BoosterHeatPumpElementData, ChillerElementData
from pandaprosumer.location_period import Period
from pandaprosumer.pandaprosumer_container import pandaprosumerContainer, get_default_prosumer_container_structure
from pandaprosumer.prosumer_toolbox import add_new_element, load_library_entry
from pandaprosumer.time_series.time_series import TimeSeries

logger = logging.getLogger()


def create_empty_prosumer_container(name="", add_basic_lib=True, fluid="water",check_order = True):
    """
    This function initializes the prosumer datastructure

    OPTIONAL:
        **name** (string, default None) - name for the prosumer

        **add_basic_lib** (bool, default True) -

        **fluid** (string or pandapipes.Fluid instance, default 'water') - The fluid used in the prosumer

    """
    prosumer = pandaprosumerContainer(get_default_prosumer_container_structure())
    prosumer['name'] = name
    # if add_basic_lib: add_basic_library(prosumer)
    add_new_element(prosumer, TimeSeries)
    prosumer['controller'] = pd.DataFrame(np.zeros(0, dtype=prosumer['controller']), index=[])
    prosumer['mapping'] = pd.DataFrame(np.zeros(0, dtype=prosumer['mapping']), index=[])
    prosumer['check_order'] = check_order

    if fluid is not None:
        if isinstance(fluid, Fluid):
            prosumer["fluid"] = fluid
        elif isinstance(fluid, str):
            create_fluid_from_lib(prosumer, fluid)
        else:
            logger.warning("The fluid %s cannot be added to the prosumer. Only fluids of type Fluid or "
                           "strings can be used." % fluid)

    return prosumer


def create_period(prosumer, resolution_s, start=None, end=None, timezone=None, name=None, index=None):
    """
    Creates a new period in prosumer["period"
    # FixMe: what if start and end are None ?

    INPUT:
        **prosumer** (pandaprosumerContainer) - The prosumer within this period should be created

        **resolution_s** (float) - The resolution of the period [s]

    OPTIONAL:
        **start** (string, default None) - The start time of the period

        **end** (string, default None) - The end time of the period

        **timezone** (string, default None) - The timezone of the period. If None, will default to 'utc'.
        Example: 'Europe/Paris'

        **name** (string, default None) - The name of the period

        **index** (string, default None) - The index of the period in the prosumer
    """
    add_new_element(prosumer, Period)

    index = _get_index_with_check(prosumer, "period", index)

    entries = dict(zip(["name", "start", "end", "resolution_s", "timezone"],
                       [name, start, end, resolution_s, timezone]))

    _set_entries(prosumer, "period", index, **entries)
    return int(index)


def create_heat_pump(prosumer,
                     delta_t_evap_c=15.,
                     carnot_efficiency=0.5,
                     pinch_c=None,
                     delta_t_hot_default_c=5,
                     max_p_comp_kw=np.nan,
                     min_p_comp_kw=np.nan,
                     max_t_cond_out_c=np.nan,
                     max_cop=np.nan,
                     cond_fluid=None,
                     evap_fluid=None,
                     name=None,
                     index=None,
                     in_service=True,
                     **kwargs):
    """
    Creates a heat pump element in prosumer["heat_pump"]

    INPUT:
        **prosumer** - The prosumer within this heat pump should be created

    OPTIONAL:
        **delta_t_evap_c** (float, default 15) - Constant temperature difference at the evaporator [C]

        **carnot_efficiency** (float, default 0.5) -

        **pinch_c** (float, default 15) -

        **delta_t_hot_default_c** (float, default 5) - Default difference between the hot (feed) temperatures [C]

        **name** (string, default None) - A custom name for this heat pump

        **index** (int, default None) - Force a specified ID if it is available. If None, the index one \
            higher than the highest already existing index is selected.

        **in_service** (boolean, default True) - True for in_service or False for out of service

        **max_p_comp_kw** (float, default None) - Power of the compressor [kW]

        **min_p_comp_kw** (float, default None) - Minimum working power of the compressor [kW]

        **max_cop** (float, default None) - Maximum COP

        **cond_fluid** (str, default None) - Fluid at the condenser. If None, the \
        prosumer's fluid will be used

        **evap_fluid** (str, default None) - Fluid at the evaporator. If None, the \
        prosumer's fluid will be used

    OUTPUT:
        **index** (int) - The unique ID of the created heat pump

    EXAMPLE:
        create_heat_pump(prosumer, "heat_pump1")
    """
    add_new_element(prosumer, HeatPumpElementData)

    index = _get_index_with_check(prosumer, "heat_pump", index)

    if not cond_fluid:
        cond_fluid = prosumer.fluid.name
    if not evap_fluid:
        evap_fluid = prosumer.fluid.name

    if cond_fluid is not None:
        if isinstance(cond_fluid, Fluid):
            cond_fluid = cond_fluid.name
    if evap_fluid is not None:
        if isinstance(evap_fluid, Fluid):
            evap_fluid = evap_fluid.name

    entries = dict(
        zip(['name', 'pinch_c', 'delta_t_evap_c', 'carnot_efficiency', 'delta_t_hot_default_c', 'max_p_comp_kw',
             'min_p_comp_kw', 'max_t_cond_out_c', 'max_cop', 'cond_fluid', 'evap_fluid', 'in_service'],
            [name, pinch_c, delta_t_evap_c, carnot_efficiency, delta_t_hot_default_c, max_p_comp_kw,
             min_p_comp_kw, max_t_cond_out_c, max_cop, cond_fluid, evap_fluid, in_service])
    )

    _set_entries(prosumer, "heat_pump", index, **entries, **kwargs)

    # _add_to_entries_if_not_nan(prosumer, "heat_pump", entries, index, "max_p_comp_kw", max_p_comp_kw)
    # _add_to_entries_if_not_nan(prosumer, "heat_pump", entries, index, "min_p_comp_kw", min_p_comp_kw)
    # _add_to_entries_if_not_nan(prosumer, "heat_pump", entries, index, "max_cop", max_cop)

    return int(index)


def create_heat_demand(prosumer,
                       scaling=1.0,
                       name=None,
                       index=None,
                       in_service=True,
                       **kwargs):
    """
    Creates a heat demand element in prosumer["heat_demand"]

    INPUT:
        **prosumer** - The prosumer within this heat demand should be created

    OPTIONAL:
        **scaling** (float, default 1) - A scaling factor applied to the heat demand.
        Multiply the demanded power by this factor

        **t_in_set_c** (float, default nan) - The default required input temperature level [C]

        **t_out_set_c** (float, default nan) - The default required output temperature level [C]

        **name** (string, default None) - A custom name for this heat demand

        **index** (int, default None) - Force a specified ID if it is available. If None, the index one \
            higher than the highest already existing index is selected.

        **in_service** (boolean, default True) - True for in_service or False for out of service

    OUTPUT:
        **index** (int) - The unique ID of the created heat demand

    EXAMPLE:
        create_heat_demand(prosumer, "heat_demand1")
    """
    add_new_element(prosumer, HeatDemandElementData)

    index = _get_index_with_check(prosumer, "heat_demand", index)

    entries = dict(zip(["name", "scaling", "in_service"],
                       [name, scaling, in_service]))

    _set_entries(prosumer, "heat_demand", index, **entries, **kwargs)

    # _add_to_entries_if_not_nan(prosumer, "heat_demand", entries, index, "t_in_set_c", t_in_set_c)
    # _add_to_entries_if_not_nan(prosumer, "heat_demand", entries, index, "t_out_set_c", t_out_set_c)

    return int(index)


def create_stratified_heat_storage(prosumer,
                                   tank_height_m,
                                   tank_internal_radius_m,
                                   tank_external_radius_m=None,
                                   insulation_thickness_m=.15,
                                   n_layers=100,
                                   min_useful_temp_c=65.,
                                   k_fluid_w_per_mk=.598,
                                   k_insu_w_per_mk=.028,
                                   k_wall_w_per_mk=45,
                                   h_ext_w_per_m2k=12.5,
                                   t_ext_c=22.5,
                                   max_remaining_capacity_kwh=1,
                                   t_discharge_out_tol_c=1e-3,
                                   max_dt_s=None,
                                   height_charge_in_m=None,
                                   height_charge_out_m=0,
                                   height_discharge_out_m=None,
                                   height_discharge_in_m=0,
                                   name=None,
                                   index=None,
                                   in_service=True,
                                   **kwargs):
    """
    Creates a stratified heat storage element in prosumer["stratified_heat_storage"]

    INPUT:
        **prosumer** - The prosumer within this stratified heat storage should be created.

        **tank_height_m** (float) - The height of the storage tank in m.

        **tank_internal_radius_m** (float) - The internal radius of the storage tank in m.

    OPTIONAL:
        **tank_external_radius_m** (float, default None) -  tank_external_radius (without insulation) [m]. If None, \
        will use tank_internal_radius_m plus 10 cm

        **insulation_thickness_m** (float, default 0.15) - insulation thickness [m]

        **n_layers** (integer, default 100) - number of layers used for the calculations

        **min_useful_temp_c** (float, default 65) - Temperature used as a threshold to calculate the amount of stored
        energy [C]

        **k_fluid_w_per_mk** (float, default 0.598) - Thermal conductivity of storage fluid (prosumer.fluid) [W/(mK)]

        **k_insu_w_per_mk** (float, default 0.028) - Thermal conductivity of insulation [W/(mK)] \
        Default: 0.028 W/(mK) (Polyurethane foam)

        **k_wall_w_per_mk** (float, default 45) - Thermal conductivity of the tank wall [W/(mK)] \
        Default: 45 W/(mK) (Steel)

        **h_ext_w_per_m2k** (float, default 12.5) - Heat transfer coefficient with the environment \
        (Convection between tank and air) [W/(m^2K)]

        **t_ext_c** (float, default 22.5) - The ambient temperature used for calculating heat losses [C]

        **max_remaining_capacity_kwh** (float, default 1) - The difference between the maximum energy that can be  \
        stored in the storage and the actual stored energy from which the storage will not require to \
        be filled anymore [kWh]

        **t_discharge_out_tol_c** (float, default 0.001) - The maximum allowed difference between the demand \
        temperature and the temperature of the top layer in the storage to allow supplying the demand [C]

        **max_dt_s** (float, default None) - The temporal resolution of the storage calculation.\
        Default to the period resolution. May cause divergence of the model if too high. [s]

        **height_charge_in_m** (float, default None) - The height of the inlet charging point in m.

        **height_charge_out_m** (float, default None) - The height of the outlet charging in m.

        **height_discharge_out_m** (float, default None) - The height of the outlet discharging point in m.

        **height_discharge_in_m** (float, default None) - The height of the outlet charging point in m.

        **name** (string, default None) - A custom name for this stratified heat storage

        **index** (int, default None) - Force a specified ID if it is available. If None, the index one \
            higher than the highest already existing index is selected.

        **in_service** (boolean, default True) - True for in_service or False for out of service

    OUTPUT:
        **index** (int) - The unique ID of the created stratified heat storage

    EXAMPLE:
        create_stratified_heat_storage(prosumer, 10, 0.6, "stratified_heat_storage_1")
    """
    add_new_element(prosumer, StratifiedHeatStorageElementData)

    if tank_external_radius_m is None:
        tank_external_radius_m = tank_internal_radius_m + .1
    if tank_external_radius_m < tank_internal_radius_m:
        raise ValueError(f"tank_external_radius_m ({tank_external_radius_m} m) must be greater "
                         f"than tank_internal_radius_m ({tank_internal_radius_m} m)")

    if (height_charge_out_m and height_charge_out_m < 0 or
            height_charge_out_m and height_charge_out_m and height_charge_in_m < height_charge_out_m or
            height_charge_out_m and height_charge_in_m > tank_height_m):
        raise ValueError(f"height_charge_out_m ({height_charge_out_m} m) or height_charge_in_m ({height_charge_in_m} m)"
                         f"is invalid.")
    if (height_discharge_in_m and height_discharge_in_m < 0 or
            height_discharge_in_m and height_discharge_in_m and height_discharge_out_m < height_discharge_in_m or
            height_discharge_in_m and height_discharge_out_m > tank_height_m):
        raise ValueError(f"height_discharge_in_m ({height_discharge_in_m} m) or "
                         f"height_discharge_out_m ({tank_height_m} m) is invalid.")

    index = _get_index_with_check(prosumer, "stratified_heat_storage", index)

    entries = dict(zip(['name', 'tank_height_m', 'tank_internal_radius_m', 'tank_external_radius_m', 'n_layers',
                        'min_useful_temp_c', 'insulation_thickness_m', 'k_fluid_w_per_mk', 'k_insu_w_per_mk',
                        'k_wall_w_per_mk', 'h_ext_w_per_m2k', 't_ext_c', 'max_remaining_capacity_kwh',
                        't_discharge_out_tol_c', 'max_dt_s', 'height_charge_in_m',
                        'height_charge_out_m', 'height_discharge_out_m', 'height_discharge_in_m', 'in_service'],
                       [name, tank_height_m, tank_internal_radius_m, tank_external_radius_m, n_layers,
                        min_useful_temp_c, insulation_thickness_m, k_fluid_w_per_mk, k_insu_w_per_mk,
                        k_wall_w_per_mk, h_ext_w_per_m2k, t_ext_c, max_remaining_capacity_kwh,
                        t_discharge_out_tol_c, max_dt_s, height_charge_in_m,
                        height_charge_out_m, height_discharge_out_m, height_discharge_in_m, in_service]))

    _set_entries(prosumer, "stratified_heat_storage", index, **entries, **kwargs)
    return int(index)


def create_heat_exchanger(prosumer,
                          t_1_in_nom_c=90,
                          t_1_out_nom_c=65,
                          t_2_in_nom_c=50,
                          t_2_out_nom_c=60,
                          mdot_2_nom_kg_per_s=0.4,
                          delta_t_hot_default_c=5,
                          max_q_kw=None,
                          min_delta_t_1_c=5,
                          primary_fluid=None,
                          secondary_fluid=None,
                          name=None,
                          index=None,
                          in_service=True,
                          **kwargs):
    """
        Creates a heat exchanger element in prosumer["heat_exchanger"]

    INPUT:
        **prosumer** - The prosumer within this heat exchanger should be created

    OPTIONAL:
        **t_1_in_nom_c** (float, default 90) - Primary nominal input temperature [C]

        **t_1_out_nom_c** (float, default 65) - Primary nominal output temperature [C]

        **t_2_in_nom_c** (float, default 50) - Secondary nominal input temperature [C]

        **t_2_out_nom_c** (float, default 60) - Secondary nominal output temperature [C]

        **mdot_2_nom_kg_per_s** (float, default 0.4) - Secondary nominal mass flow [kg/s]

        **delta_t_hot_default_c** (float, default 5) - Default difference between the hot (feed) temperatures [C]

        **max_q_kw** (float, default None) - Maximum heat power through the heat exchanger [kW]

        **min_delta_t_1_c** (float, default 5) - Minimum temperature difference at the primary side [C]

        **primary_fluid** (string, default None)* - Fluid at the primary side of the heat exchanger. If None, the \
        prosumer's fluid will be used

        **secondary_fluid** (string, default None) - Fluid at the secondary side of the heat exchanger. If None, the \
        prosumer's fluid will be used

        **name** (string, default None) - The name for this heat exchanger

        **index** (int, default None) - Force a specified ID if it is available. If None, the index one \
            higher than the highest already existing index is selected.

        **in_service** (boolean, default True) - True for in_service or False for out of service

    OUTPUT:
        **index** (int) - The unique ID of the created heat exchanger

    EXAMPLE:
        create_heat_exchanger(prosumer, "heat_exchanger1")
    """
    add_new_element(prosumer, HeatExchangerElementData)

    if t_1_in_nom_c < t_1_out_nom_c:
        raise ValueError(f"The nominal input temperature at the primary side of the heat exchanger t_1_in_nom_c "
                         f"({t_1_in_nom_c}) must be greater than the output temperature t_1_out_nom_c ({t_1_out_nom_c})")
    if t_2_in_nom_c > t_2_out_nom_c:
        raise ValueError(f"The nominal input temperature at the secondary side of the heat exchanger t_2_in_nom_c "
                         f"({t_2_in_nom_c}) must be smaller than the output temperature t_2_out_nom_c ({t_2_out_nom_c})")

    index = _get_index_with_check(prosumer, "heat_exchanger", index)

    if not primary_fluid:
        primary_fluid = prosumer.fluid.name
    if not secondary_fluid:
        secondary_fluid = prosumer.fluid.name

    if primary_fluid is not None:
        if isinstance(primary_fluid, Fluid):
            primary_fluid = primary_fluid.name
    if secondary_fluid is not None:
        if isinstance(secondary_fluid, Fluid):
            secondary_fluid = secondary_fluid.name

    entries = dict(zip(["name", "t_1_in_nom_c", "t_1_out_nom_c", "t_2_in_nom_c", "t_2_out_nom_c", "mdot_2_nom_kg_per_s",
                        "delta_t_hot_default_c", "max_q_kw", "min_delta_t_1_c", "primary_fluid", "secondary_fluid",
                        "in_service"],
                       [name, t_1_in_nom_c, t_1_out_nom_c, t_2_in_nom_c, t_2_out_nom_c, mdot_2_nom_kg_per_s,
                        delta_t_hot_default_c, max_q_kw, min_delta_t_1_c, primary_fluid, secondary_fluid,
                        in_service]))

    _set_entries(prosumer, "heat_exchanger", index, **entries, **kwargs)
    return int(index)


def create_dry_cooler(prosumer,
                      n_nom_rpm,
                      p_fan_nom_kw,
                      qair_nom_m3_per_h,
                      t_air_in_nom_c=15,
                      t_air_out_nom_c=35,
                      t_fluid_in_nom_c=65,
                      t_fluid_out_nom_c=40,
                      fans_number=1,
                      adiabatic_mode=False,
                      phi_adiabatic_sat_percent=99,
                      min_delta_t_air_c=0,
                      name=None,
                      index=None,
                      in_service=True,
                      **kwargs):
    """
        Creates a dry cooler element in prosumer["dry_cooler"]

    INPUT:
        **prosumer** - The prosumer within this dry_cooler should be created

        **n_nom_rpm** (float) - Nominal rotational speed of the fans [rpm]

        **p_fan_nom_kw** (float) - Nominal electric power of each fan [kW]

        **qair_nom_m3_per_h** (float) - Nominal air flow [m3/h]

        **t_air_in_nom_c** (float, default 15) - Air nominal input temperature [C]

        **t_air_out_nom_c** (float, default 35) - Air nominal output temperature [C]

        **t_fluid_in_nom_c** (float, default 60) - Water nominal input temperature [C]

        **t_fluid_out_nom_c** (float, default 40) - Water nominal output temperature [C]

    OPTIONAL:
        **fans_number** (integer, default 1) - Number of fans in the dry cooler

        **adiabatic_mode** (boolean, default False) - Whether to use the air adiabatic pre-cooling mode.
            If False, apply dry cooling only

        **phi_adiabatic_sat_percent** (float, default 99) - Adiabatic Pre-Cooling saturation level [%]

        **min_delta_t_air_c** (float, default 0) - Minimum air temperature difference [C]

        **name** (string, default None) - The name for this dry cooler

        **index** (int, default None) - Force a specified ID if it is available. If None, the index one \
            higher than the highest already existing index is selected.

        **in_service** (boolean, default True) - True for in_service or False for out of service

    OUTPUT:
        **index** (int) - The unique ID of the created dry cooler

    EXAMPLE:
        create_dry_cooler(prosumer, "dry_cooler_1")
    """
    add_new_element(prosumer, DryCoolerElementData)

    index = _get_index_with_check(prosumer, "dry_cooler", index)

    entries = dict(zip(["name", "n_nom_rpm", "p_fan_nom_kw", "qair_nom_m3_per_h", "t_air_in_nom_c", "t_air_out_nom_c",
                        "t_fluid_in_nom_c", "t_fluid_out_nom_c", "fans_number",
                        "adiabatic_mode", "phi_adiabatic_sat_percent", "min_delta_t_air_c", "in_service"],
                       [name, n_nom_rpm, p_fan_nom_kw, qair_nom_m3_per_h, t_air_in_nom_c, t_air_out_nom_c,
                        t_fluid_in_nom_c, t_fluid_out_nom_c, fans_number,
                        adiabatic_mode, phi_adiabatic_sat_percent, min_delta_t_air_c, in_service]))

    _set_entries(prosumer, "dry_cooler", index, **entries, **kwargs)
    return int(index)


def create_electric_boiler(prosumer,
                           max_p_kw,
                           efficiency_percent=100,
                           name=None,
                           index=None,
                           in_service=True,
                           **kwargs):
    """
        Creates an electric boiler element in prosumer["electric_boiler"]

    INPUT:
        **prosumer** - The prosumer within this electric boiler should be created

        **max_p_kw** (float) - Maximal electrical power of the boiler [kW]

    OPTIONAL:
        **efficiency_percent** (float, default 100) - Boiler Efficiency [%]

        **name** (string, default None) - The name for this electric boiler

        **index** (int, default None) - Force a specified ID if it is available. If None, the index one \
            higher than the highest already existing index is selected.

        **in_service** (boolean, default True) - True for in_service or False for out of service

    OUTPUT:
        **index** (int) - The unique ID of the created electric boiler

    EXAMPLE:
        create_electric_boiler(prosumer, "electric_boiler_1")
    """
    add_new_element(prosumer, ElectricBoilerElementData)

    index = _get_index_with_check(prosumer, "electric_boiler", index)

    entries = dict(zip(["name", "max_p_kw", "efficiency_percent", "in_service"],
                       [name, max_p_kw, efficiency_percent, in_service]))

    _set_entries(prosumer, "electric_boiler", index, **entries, **kwargs)
    return int(index)


def create_gas_boiler(prosumer,
                           max_q_kw,
                           heating_value_kj_per_kg=50e3,
                           efficiency_percent=100,
                           name=None,
                           index=None,
                           in_service=True,
                           **kwargs):
    """
        Creates an gas boiler element in prosumer["gas_boiler"]

    INPUT:
        **prosumer** - The prosumer within this gas boiler should be created

        **max_q_kw** (float) - Maximal heat power of the boiler [kW]

        **heating_value_kj_per_kg** (float, default 50e3) - Heating Value of the gas (amount of energy per kg of gas) [kJ/kg]

    OPTIONAL:
        **efficiency_percent** (float, default 100) - Boiler Efficiency [%]

        **name** (string, default None) - The name for this gas boiler

        **index** (int, default None) - Force a specified ID if it is available. If None, the index one \
            higher than the highest already existing index is selected.

        **in_service** (boolean, default True) - True for in_service or False for out of service

    OUTPUT:
        **index** (int) - The unique ID of the created gas boiler

    EXAMPLE:
        create_gas_boiler(prosumer, "gas_boiler_1")
    """
    add_new_element(prosumer, GasBoilerElementData)

    index = _get_index_with_check(prosumer, "gas_boiler", index)

    entries = dict(zip(["name", "max_q_kw", "heating_value_kj_per_kg", "efficiency_percent", "in_service"],
                       [name, max_q_kw, heating_value_kj_per_kg, efficiency_percent, in_service]))

    _set_entries(prosumer, "gas_boiler", index, **entries, **kwargs)
    return int(index)


def create_booster_heat_pump(
    prosumer,
    hp_type,
    in_service=True,
    name=None,
    index=None,
    **kwargs
):
    """
    :param prosumer:
    :param in_service:  (Default value = True)
    :param name:  (Default value = None)
    :param index:  (Default value = None)

    """
    add_new_element(prosumer, BoosterHeatPumpElementData)

    index = _get_index_with_check(prosumer, "booster_heat_pump", index)

    entries = dict(
        zip(
            [
                "name",
                "hp_type",
                "in_service",
            ],
            [
                name,
                hp_type,
                in_service,
            ],
        )
    )

    _set_entries(prosumer, "booster_heat_pump", index, **entries, **kwargs)
    return int(index)

def create_ice_chp(prosumer, size, fuel, altitude=0, in_service=True, name=None, index=None, **kwargs):
    add_new_element(prosumer, IceChpElementData)

    index = _get_index_with_check(prosumer, "ice_chp", index)

    entries = dict(
        zip(
            [
                "name",
                "size",
                "fuel",
                "altitude",
                "in_service",
            ],
            [
                name,
                size,
                fuel,
                altitude,
                in_service,
            ],
        )
    )

    _set_entries(prosumer, "ice_chp", index, **entries, **kwargs)
    return int(index)

def create_heat_storage(prosumer,
                        q_capacity_kwh=0.,
                        in_service=True,
                        index=None,
                        name=None,
                        **kwargs):

    add_new_element(prosumer, HeatStorageElementData)

    index = _get_index_with_check(prosumer, "heat_storage", index)

    entries = dict(zip(['name', 'q_capacity_kwh', 'in_service'], [name, q_capacity_kwh, in_service]))

    _set_entries(prosumer, "heat_storage", index, **entries, **kwargs)
    return int(index)

def create_chiller(
        prosumer,
        cp_water=4.18,
        t_sh=5.0,  # °C of super heating in the evaporator
        t_sc=2.0,
        pp_cond=5.0,
        pp_evap=5.0,
        plf_cc=0.9,
        w_evap_pump=200.0,
        w_cond_pump=200.0,
        eng_eff=1.0,
        n_ref="R410A",
        in_service=True,
        index=None,
        name=None,
        **kwargs):

    """Adds a new chiller to the list of prosumer elements and defines its datasheet values

    :param prosumer: Empty prosumer container
    :type prosumer: object of type prosumer
    :param cp_water: Fluid specific heat capacity, units kJ/kgK, by default 4.18
    :type cp_water: float, optional
    :param t_sh: Degrees of superheating in the evaporator, units K, by default 5.0
    :type t_sh: float, optional
    :param t_sc: Degrees of subcooling in the condenser, units K, by default 5.0
    :type t_sc: float, optional
    :param pp_cond: Minimum temperature difference between fluids in the condenser, units K, by default 5.0
    :type pp_cond: float, optional
    :param pp_evap: Minimum temperature difference between fluids in the evaporator, units K, by default 5.0
    :type pp_evap: float, optional
    :param plf_cc: Partial load correction coefficient for all/nothing chillers, by default 0.9
    :type plf_cc: float, optional
    :param w_evap_pump: Evaporator pump electrical power,units kJ/h, by default 200.0
    :type w_evap_pump: float, optional
    :param w_cond_pump: Condenser pump electrical power,units kJ/h, by default 200.0
    :type w_cond_pump: float, optional
    :param eng_eff: Motor performance, by default 1.0
    :type eng_eff: float, optional
    :param n_ref: Refrigerant code, by default 'R410A', full list of codes here: http://www.coolprop.org/fluid_properties/PurePseudoPure.html#list-of-fluids
    :type n_ref: string, optional
    :param in_service: _description_, by default True
    :type in_service: bool, optional
    :param index: zero based index position of the element in the list, by default None
    :type index: _type_, optional
    :param # °C of super heating in the evaporatort_sc:  (Default value = 2.0)
    :param # name:  (Default value = None)


    """
    add_new_element(
        prosumer, ChillerElementData
    )

    index = _get_index_with_check(prosumer, "sn_chiller", index)

    entries = dict(
        zip(
            [
                "name",
                "cp_water",
                "t_sh",
                "t_sc",
                "pp_cond",
                "pp_evap",
                "plf_cc",
                "w_evap_pump",
                "w_cond_pump",
                "eng_eff",
                "n_ref",
                "in_service"

            ],
            [
                name,
                cp_water,
                t_sh,
                t_sc,
                pp_cond,
                pp_evap,
                plf_cc,
                w_evap_pump,
                w_cond_pump,
                eng_eff,
                n_ref,
                in_service

            ],
        )
    )

    _set_entries(prosumer, "sn_chiller", index, **entries, **kwargs)
    return int(index)
