from pandaprosumer.controller.models.heat_pump import HeatPumpController
from pandaprosumer.create import *
from pandaprosumer.controller.models import *
from pandaprosumer.controller.data_model import *
from pandaprosumer.controller import *
import numpy as np


def create_controlled_const_profile(prosumer, input_columns, result_columns, period, data_source, level=0, order=0,  temp_fluid_map_idx = None,
                                                              mdot_fluid_map_idx = None):
    const_controller_data = ConstProfileControllerData(
        input_columns=input_columns,
        result_columns=result_columns,
        period_index=period,
    )
    const_profile = ConstProfileController(prosumer,
                                           const_object=const_controller_data,
                                           df_data=data_source,
                                           order=order,
                                           level=level,
                                           temp_fluid_map_idx=temp_fluid_map_idx,
                                           mdot_fluid_map_idx=mdot_fluid_map_idx)
    return const_profile.index



def create_controlled_heat_pump(prosumer,
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
                                level = 0,
                                order = 0,
                                period = 0,
                                 **kwargs):
    """
        Creates a heat pump element in prosumer["heat_pump"] and an heat pump controller

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

            **level** (int, default 0) - The level of the controller

            **order** (int, default 0) - The order of the controller

            **period** (int, default 0) - Index of the period, default is 0

        OUTPUT:
            **index** (int) - The unique ID of the created heat pump controller

        EXAMPLE:
            create_controlled_heat_pump(prosumer, "heat_pump1")
        """


    heat_pump_index = create_heat_pump(
        prosumer,
        **{k: v for k, v in locals().items() if k not in {"prosumer", "period", "order","level","kwargs"}},
        **kwargs
    )
    heat_pump_controller_data = HeatPumpControllerData(
        element_name='heat_pump',
        element_index=[heat_pump_index],
        period_index=period
    )
    heat_pump = HeatPumpController(prosumer,
                                   heat_pump_controller_data,
                                   order=order,
                                   level=level,
                                   name='heat_pump_controller')
    return heat_pump.index



def create_controlled_heat_demand(prosumer,
                                    scaling=1.0,
                                    name=None,
                                    index=None,
                                    in_service=True,
                                  period = 0,
                                  level = 0,
                                  order = 0,
                                    **kwargs):
    """
        Creates a heat demand element and a controller in prosumer["heat_demand"] and an heat demand controller

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

            **level** (int, default 0) - The level of the controller

            **order** (int, default 0) - The order of the controller

            **period** (int, default 0) - Index of the period, default is 0

        OUTPUT:
            **index** (int) - The unique ID of the created heat demand controller

        EXAMPLE:
            create_controlled_heat_demand(prosumer, "heat_demand1")
        """


    heat_demand_index = create_heat_demand(
        prosumer,
        **{k: v for k, v in locals().items() if k not in {"prosumer", "period", "order","level", "kwargs"}},
        **kwargs
    )
    heat_demand_controller_data = HeatDemandControllerData(
        element_name='heat_demand',
        element_index=[heat_demand_index],
        period_index=period
    )
    heat_demand_controller = HeatDemandController(prosumer,
                                                  heat_demand_controller_data,
                                                  order=order,
                                                  level=level,
                                                  name='heat_demand_controller')
    return heat_demand_controller.index


def create_controlled_stratified_heat_storage(prosumer,
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
                                              level=0,
                                              order=0,
                                              period=0,
                                              init_layer_temps_c=None,
                                              plot=False,
                                              bypass=True,
                                              **kwargs):
    """
        Creates a stratified heat storage element in prosumer["stratified_heat_storage"] and a stratified heat storage controller

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

            **level** (int, default 0) - The level of the controller

            **order** (int, default 0) - The order of the controller

            **period** (int, default 0) - Index of the period, default is 0

            **init_layer_temps_c** (float list, default None) - Initial state of charge

        OUTPUT:
            **index** (int) - The unique ID of the created stratified heat storage

        EXAMPLE:
            create_controlled_stratified_heat_storage(prosumer, 10, 0.6, "stratified_heat_storage_1")
        """

    shs_index = create_stratified_heat_storage(
        prosumer,
        **{k: v for k, v in locals().items() if k not in {"prosumer", "period", "order", "level",
                                                          'init_layer_temps_c', 'plot', 'bypass', "kwargs"}},
        **kwargs
    )
    stratified_heat_storage_controller_data = StratifiedHeatStorageControllerData(
        element_name='stratified_heat_storage',
        element_index=[shs_index],
        period_index=period
    )
    stratified_heat_storage_controller = StratifiedHeatStorageController(prosumer,
                                                                         stratified_heat_storage_controller_data,
                                                                         order=order,
                                                                         level=level,
                                                                         init_layer_temps_c=init_layer_temps_c,
                                                                         plot=plot,
                                                                         bypass=bypass,
                                                                         name='stratified_heat_storage_controller')
    return stratified_heat_storage_controller.index


def create_controlled_heat_exchanger(prosumer,
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
                                     level = 0,
                                     order = 0,
                                     period = 0,
                                    **kwargs):
    """
            Creates a heat exchanger element in prosumer["heat_exchanger"] and an heat exchanger controller

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

            **level** (int, default 0) - The level of the controller

            **order** (int, default 0) - The order of the controller

            **period** (int, default 0) - Index of the period, default is 0

        OUTPUT:
            **index** (int) - The unique ID of the created heat exchanger

        EXAMPLE:
            create_controlled_heat_exchanger(prosumer, "heat_exchanger1")
        """

    heat_exchanger_index = create_heat_exchanger(
        prosumer,
        **{k: v for k, v in locals().items() if k not in {"prosumer", "period","order","level","kwargs"}},
        **kwargs
    )
    heat_exchanger_controller_data = HeatExchangerControllerData(
        element_name='heat_exchanger',
        element_index=[heat_exchanger_index],
        period_index=period,
        **kwargs
    )
    heat_exchanger_controller = HeatExchangerController(prosumer,
                                                        heat_exchanger_controller_data,
                                                        order=order,
                                                        level=level,
                                                        name='heat_exchanger_controller')
    return heat_exchanger_controller.index


def create_controlled_electric_boiler(prosumer,
                                       max_p_kw,
                                       efficiency_percent=100,
                                       name=None,
                                       index=None,
                                       in_service=True,
                                      level =0,
                                      order = 0,
                                      period = 0,
                                       **kwargs):
    """
            Creates an electric boiler element in prosumer["electric_boiler"] and an electric boiler controller

        INPUT:
            **prosumer** - The prosumer within this electric boiler should be created

            **max_p_kw** (float) - Maximal electrical power of the boiler [kW]

        OPTIONAL:
            **efficiency_percent** (float, default 100) - Boiler Efficiency [%]

            **name** (string, default None) - The name for this electric boiler

            **index** (int, default None) - Force a specified ID if it is available. If None, the index one \
                higher than the highest already existing index is selected.

            **in_service** (boolean, default True) - True for in_service or False for out of service

            **level** (int, default 0) - The level of the controller

            **order** (int, default 0) - The order of the controller

            **period** (int, default 0) - Index of the period, default is 0

        OUTPUT:
            **index** (int) - The unique ID of the created electric boiler

        EXAMPLE:
            create_controlled_electric_boiler(prosumer, "electric_boiler_1")
        """

    electric_boiler_index = create_electric_boiler(
        prosumer,
        **{k: v for k, v in locals().items() if k not in {"prosumer", "period","order",'level','kwargs'}},
    **kwargs)
    electric_boiler_controller_data = ElectricBoilerControllerData(
        element_name='electric_boiler',
        element_index=[electric_boiler_index],
        period_index=period,
        **kwargs
    )
    electric_boiler_controller = ElectricBoilerController(prosumer,
                                                          electric_boiler_controller_data,
                                                          order=order,
                                                          level=level,
                                                          name='electric_boiler_controller')
    return electric_boiler_controller.index


def create_controlled_gas_boiler(prosumer,
                                   max_q_kw,
                                   heating_value_kj_per_kg = 50e3,
                                   efficiency_percent=100,
                                   name=None,
                                   index=None,
                                   in_service=True,
                                 period = 0,
                                 level = 0,
                                 order = 0,
                                    **kwargs):
    """
            Creates an gas boiler element in prosumer["gas_boiler"] and a gas boiler controller

        INPUT:
            **prosumer** - The prosumer within this gas boiler should be created

            **max_q_kw** (float) - Maximal heat power of the boiler [kW]


        OPTIONAL:
            **heating_value_kj_per_kg** (float, default 50e3) - Heating Value of the gas (amount of energy per kg of gas) [kJ/kg]

            **efficiency_percent** (float, default 100) - Boiler Efficiency [%]

            **name** (string, default None) - The name for this gas boiler

            **index** (int, default None) - Force a specified ID if it is available. If None, the index one \
                higher than the highest already existing index is selected.

            **in_service** (boolean, default True) - True for in_service or False for out of service

            **level** (int, default 0) - The level of the controller

            **order** (int, default 0) - The order of the controller

            **period** (int, default 0) - Index of the period, default is 0



        OUTPUT:
            **index** (int) - The unique ID of the created gas boiler

        EXAMPLE:
            create_controlled_gas_boiler(prosumer, "gas_boiler_1")
        """

    gas_boiler_index = create_gas_boiler(
        prosumer,
        **{k: v for k, v in locals().items() if k not in {"prosumer", "period","order",'level','kwargs'}},
    **kwargs)
    gas_boiler_controller_data = GasBoilerControllerData(
        element_name='gas_boiler',
        element_index=[gas_boiler_index],
        period_index=period,
        **kwargs
    )
    gas_boiler_controller = GasBoilerController(prosumer,
                                                gas_boiler_controller_data,
                                                order=order,
                                                level=level,
                                                name='gas_boiler_controller')
    return gas_boiler_controller.index


def create_controlled_dry_cooler(prosumer,
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
                                    period = 0,
                                    level = 0,
                                 order = 0,
                                    **kwargs):
    """
           Creates a dry cooler element in prosumer["dry_cooler"] and a dry cooler controller

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

           **level** (int, default 0) - The level of the controller

            **order** (int, default 0) - The order of the controller

            **period** (int, default 0) - Index of the period, default is 0

       OUTPUT:
           **index** (int) - The unique ID of the created dry cooler

       EXAMPLE:
           create_controlled_dry_cooler(prosumer, "dry_cooler_1")
       """

    dry_cooler_index = create_dry_cooler(
        prosumer,
        **{k: v for k, v in locals().items() if k not in {"prosumer", "period","order",'level','kwargs'}},
        **kwargs
    )

    dry_cooler_controller_data = DryCoolerControllerData(
        element_name='dry_cooler',
        element_index=[dry_cooler_index],
        period_index=period,
        **kwargs
    )
    dry_cooler_controller = DryCoolerController(prosumer,
                                                dry_cooler_controller_data,
                                                order=order,
                                                level=level,
                                                name='dry_cooler_controller')
    return dry_cooler_controller.index


def create_controlled_booster_heat_pump(prosumer, hp_type, name=None, index=None, in_service=True, level=0, order=0, period=0, **kwargs):
    bhp_index = create_booster_heat_pump(prosumer, hp_type, in_service, name, index, **kwargs)
    bhp_controller_data = BoosterHeatPumpControllerData(element_name='booster_heat_pump',
        element_index=[bhp_index],
        period_index=period
    )
    bhp = BoosterHeatPumpController(prosumer,
                                   bhp_controller_data,
                                   order=order,
                                   level=level,
                                   name='heat_pump_controller')

    return bhp.index

def create_controlled_booster_heat_pump_sdewes(prosumer, hp_type, name=None, index=None, in_service=True, level=0, order=0, period=0, **kwargs):
    bhp_index = create_booster_heat_pump(prosumer, hp_type, in_service, name, index, **kwargs)
    from pandaprosumer.controller.data_model.booster_heat_pump_sdewes import BoosterHeatPumpControllerData
    bhp_controller_data = BoosterHeatPumpControllerData(element_name='booster_heat_pump',
        element_index=[bhp_index],
        period_index=period
    )
    from pandaprosumer.controller.models.booster_heat_pump_sdewes import BoosterHeatPumpController
    bhp = BoosterHeatPumpController(prosumer,
                                   bhp_controller_data,
                                   order=order,
                                   level=level,
                                   name='heat_pump_controller')

    return bhp.index

def create_controlled_ice_chp(prosumer, chp_size, fuel, altitude, name=None, index=None, in_service=True, level=0, order=0, period=0):
    ice_chp_index = create_ice_chp(prosumer, chp_size, fuel, altitude, name=name)
    ice_chp_controller_data = IceChpControllerData(
        element_name='ice_chp',
        element_index=[ice_chp_index],
        period_index=period
    )
    ice_chp = IceChpController(prosumer,
                               ice_chp_controller_data,
                               order=order,
                               level=level,
                               name='ice_chp_controller')
    return ice_chp.index