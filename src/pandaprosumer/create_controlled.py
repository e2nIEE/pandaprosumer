from pandaprosumer.create import *
from pandaprosumer.controller import *
from pandaprosumer.supervisor import *
from pandaprosumer.energy_system.control.controller.coupling.network_coupling import NetworkCouplingControl
from pandaprosumer.energy_system.control.controller.data_model.network_coupling import NetworkCouplingData


def create_controlled_network_coupling(net,
                                       element_index,
                                       element_name='heat_consumer',
                                       input_columns=[],
                                       result_columns=[],
                                       temp_fluid_map_input_col=[],
                                       mdot_fluid_map_input_col=[],
                                       temp_fluid_map_output_idx=None,
                                       mdot_fluid_map_output_idx=None,
                                       level=0,
                                       order=0,
                                       name=None):
    if isinstance(element_index, (np.integer, int)):
        element_index = [int(element_index)]
    elif isinstance(element_index, np.ndarray):
        element_index = [int(i) for i in element_index.tolist()]
    elif isinstance(element_index, list):
        element_index = [int(i) for i in element_index]

    networkcoupling = NetworkCouplingData(element_index=element_index,
                                          element_name=element_name,
                                          input_columns=input_columns,
                                          result_columns=result_columns)

    n = NetworkCouplingControl(net,
                               networkcoupling,
                               temp_fluid_map_input_col=temp_fluid_map_input_col,
                               mdot_fluid_map_input_col=mdot_fluid_map_input_col,
                               temp_fluid_map_output_idx=temp_fluid_map_output_idx,
                               mdot_fluid_map_output_idx=mdot_fluid_map_output_idx,
                               level=level, order=order, name=name)

    return n.index


def create_controlled_const_profile(prosumer,
                                    input_columns,
                                    result_columns,
                                    data_source,
                                    period=0,
                                    level=0,
                                    order=0,
                                    name=None,
                                    in_service=True,
                                    temp_fluid_map_idx=None,
                                    mdot_fluid_map_idx=None):
    const_controller_data = ConstProfileControllerData(
        input_columns=input_columns,
        result_columns=result_columns,
        period_index=period
    )
    const_profile = ConstProfileController(prosumer,
                                           const_object=const_controller_data,
                                           df_data=data_source,
                                           name=name,
                                           in_service=in_service,
                                           level=level,
                                           order=order,
                                           temp_fluid_map_idx=temp_fluid_map_idx,
                                           mdot_fluid_map_idx=mdot_fluid_map_idx)
    return const_profile.index


def create_controlled_supervisor(prosumer,
                                 input_columns,
                                 period=0,
                                 level=0,
                                 order=0):
    spdata = SupervisorData(
        input_columns=input_columns,
        result_columns=input_columns
    )
    supervisor = Supervisor(prosumer,
                            supervisor_object=spdata,
                            period_index=period,
                            level=level,
                            order=order)

    return supervisor.index


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
                                level=0,
                                order=0,
                                period=0,
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
        **{k: v for k, v in locals().items() if k not in {"prosumer", "period", "order", "level", "kwargs"}},
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
                                   name=name)
    return heat_pump.index


def create_controlled_heat_demand(prosumer,
                                  scaling=1.0,
                                  name=None,
                                  index=None,
                                  in_service=True,
                                  period=0,
                                  level=0,
                                  order=0,
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
        **{k: v for k, v in locals().items() if k not in {"prosumer", "period", "order", "level", "kwargs"}},
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
                                                  name=name)
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
                                                                         name=name)
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
                                     level=0,
                                     order=0,
                                     period=0,
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
        **{k: v for k, v in locals().items() if k not in {"prosumer", "period", "order", "level", "kwargs"}},
        **kwargs
    )
    heat_exchanger_controller_data = HeatExchangerControllerData(
        element_name='heat_exchanger',
        element_index=[heat_exchanger_index],
        period_index=period
    )
    heat_exchanger_controller = HeatExchangerController(prosumer,
                                                        heat_exchanger_controller_data,
                                                        order=order,
                                                        level=level,
                                                        name=name)
    return heat_exchanger_controller.index


def create_controlled_electric_boiler(prosumer,
                                      max_p_kw,
                                      efficiency_percent=100,
                                      name=None,
                                      index=None,
                                      in_service=True,
                                      level=0,
                                      order=0,
                                      period=0,
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
        **{k: v for k, v in locals().items() if k not in {"prosumer", "period", "order", 'level', 'kwargs'}},
        **kwargs)
    electric_boiler_controller_data = ElectricBoilerControllerData(
        element_name='electric_boiler',
        element_index=[electric_boiler_index],
        period_index=period
    )
    electric_boiler_controller = ElectricBoilerController(prosumer,
                                                          electric_boiler_controller_data,
                                                          order=order,
                                                          level=level,
                                                          name=name)
    return electric_boiler_controller.index


def create_controlled_gas_boiler(prosumer,
                                 max_q_kw,
                                 heating_value_kj_per_kg=50e3,
                                 efficiency_percent=100,
                                 name=None,
                                 index=None,
                                 in_service=True,
                                 period=0,
                                 level=0,
                                 order=0,
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
        **{k: v for k, v in locals().items() if k not in {"prosumer", "period", "order", 'level', 'kwargs'}},
        **kwargs)
    gas_boiler_controller_data = GasBoilerControllerData(
        element_name='gas_boiler',
        element_index=[gas_boiler_index],
        period_index=period
    )
    gas_boiler_controller = GasBoilerController(prosumer,
                                                gas_boiler_controller_data,
                                                order=order,
                                                level=level,
                                                name=name)
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
                                 period=0,
                                 level=0,
                                 order=0,
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
        **{k: v for k, v in locals().items() if k not in {"prosumer", "period", "order", 'level', 'kwargs'}},
        **kwargs
    )

    dry_cooler_controller_data = DryCoolerControllerData(
        element_name='dry_cooler',
        element_index=[dry_cooler_index],
        period_index=period
    )
    dry_cooler_controller = DryCoolerController(prosumer,
                                                dry_cooler_controller_data,
                                                order=order,
                                                level=level,
                                                name=name)
    return dry_cooler_controller.index


def create_controlled_booster_heat_pump(prosumer, hp_type, name=None, q_max_kw=None, index=None, in_service=True, level=0, order=0, period=0, **kwargs):
    """
               Creates a BHP element in prosumer["booster_heat_pump"] and a BHP controller

           INPUT:
               **prosumer** - The prosumer within this booster_heat_pump should be created

               **hp_type** (string) - BHP's type. Possible values are "water-water1", "water-water2", "air-water"

           OPTIONAL:
                **q_max_kw** (float, default None) - Maximum thermal power BHP [kW]

               **name** (string, default None) - The name of the BHP instance

               **index** (int, default None) - Force a specified ID if it is available. If None, the index one \
                   higher than the highest already existing index is selected.

               **in_service** (boolean, default True) - True for in_service or False for out of service

               **level** (int, default 0) - The level of the controller

                **order** (int, default 0) - The order of the controller

                **period** (int, default 0) - Index of the period, default is 0

           OUTPUT:
               **index** (int) - The unique ID of the created BHP

           EXAMPLE:
               create_controlled_booster_heat_pump(prosumer, 'water-water1', 'example_bhp')
           """
    bhp_index = create_booster_heat_pump(prosumer, hp_type, q_max_kw, in_service, name, index, **kwargs)
    bhp_controller_data = BoosterHeatPumpControllerData(element_name='booster_heat_pump',
        element_index=[bhp_index],
        period_index=period
    )
    bhp = BoosterHeatPumpController(prosumer,
                                   bhp_controller_data,
                                   order=order,
                                   level=level,
                                   name=name)

    return bhp.index


def create_controlled_ice_chp(prosumer,
                              size,
                              fuel,
                              altitude,
                              name=None,
                              index=None,
                              in_service=True,
                              level=0,
                              order=0,
                              period=0,
                              **kwargs):
    """
           Creates an ICE CHP element in prosumer["ice_chp"] and an ICE CHP controller

       INPUT:
           **prosumer** - The prosumer within this ice_chp should be created

           **size** (float) - ICE CHP rating [kW]

           **fuel** (string) - Type of the fuel used in the calculation

           **altitude** (float) - Altitude above sea level of the ICE CHP installation site [m]

       OPTIONAL:
           **name** (string, default None) - The name of the ICE CHP instance

           **index** (int, default None) - Force a specified ID if it is available. If None, the index one \
               higher than the highest already existing index is selected.

           **in_service** (boolean, default True) - True for in_service or False for out of service

           **level** (int, default 0) - The level of the controller

            **order** (int, default 0) - The order of the controller

            **period** (int, default 0) - Index of the period, default is 0

       OUTPUT:
           **index** (int) - The unique ID of the created ICE CHP

       EXAMPLE:
           create_controlled_ice_chp(prosumer, 350, "ng", 0, "example_ice_chp")
       """
    ice_chp_index = create_ice_chp(prosumer, size, fuel, altitude, name, in_service, index, **kwargs)
    ice_chp_controller_data = IceChpControllerData(
        element_name='ice_chp',
        element_index=[ice_chp_index],
        period_index=period
    )
    ice_chp = IceChpController(prosumer,
                               ice_chp_controller_data,
                               order=order,
                               level=level,
                               name=name)
    return ice_chp.index


def create_controlled_chiller(prosumer, cp_water=4.18, t_sh=5.0, t_sc=2.0, pp_cond=5.0,
                              pp_evap=5.0, plf_cc=0.9,
                              w_evap_pump=200.0, w_cond_pump=200.0,
                              eng_eff=1.0, n_ref="R410A",
                              name=None,
                              index=None,
                              in_service=True,
                              period=0,
                              level=0,
                              order=0,
                              **kwargs):
    """
    Creates a chiller element in prosumer["chiller"] and a chiller controller.

    INPUT:
        **prosumer** - The prosumer within which this chiller should be created.

        **max_q_kw** (float) - Maximal cooling power of the chiller [kW].

    OPTIONAL:
        **cooling_value_kj_per_kg** (float, default 200e3) - Cooling Value of the refrigerant [kJ/kg].

        **efficiency_percent** (float, default 100) - Chiller Efficiency [%].

        **name** (string, default None) - The name for this chiller.

        **index** (int, default None) - Force a specified ID if it is available. If None, the index one higher than the highest already existing index is selected.

        **in_service** (boolean, default True) - True for in_service or False for out of service.

        **level** (int, default 0) - The level of the controller.

        **order** (int, default 0) - The order of the controller.

        **period** (int, default 0) - Index of the period, default is 0.

    OUTPUT:
        **index** (int) - The unique ID of the created chiller.

    EXAMPLE:
        create_controlled_chiller(prosumer, "chiller_1")
    """

    chiller_index = create_chiller(
        prosumer,
        **{k: v for k, v in locals().items() if k not in {"prosumer", "period", "order", "level", "kwargs"}},
        **kwargs)

    chiller_controller_data = ChillerControllerData(
        element_name='sn_chiller',
        element_index=[chiller_index],
        period_index=period
    )

    chiller_controller = ChillerController(prosumer,
                                           chiller_controller_data,
                                           order=order,
                                           level=level,
                                           name=name)
    return chiller_controller.index


def create_controlled_heat_storage(prosumer,
                                   q_capacity_kwh=0.,
                                   name=None,
                                   index=None,
                                   in_service=True,
                                   level=0,
                                   order=0,
                                   init_soc=0.,
                                   period=0,
                                   **kwargs):
    """
    Creates a heat storage element in the prosumer and a heat storage controller.

    INPUT:
        **prosumer** - The prosumer within which this heat storage should be created.

        **q_capacity_kwh** (float) - The thermal energy capacity of the heat storage [kWh].

    OPTIONAL:
        **name** (string, default None) - The name for this heat storage controller.

        **index** (int, default None) - Force a specified ID if it is available. If None, the index one higher than the highest already existing index is selected.

        **in_service** (boolean, default True) - True for in_service or False for out of service.

        **level** (int, default 0) - The level of the controller.

        **order** (int, default 0) - The order of the controller.

        **init_soc** (float, default 0.) - The initial state of charge of the heat storage.

        **period** (int, default 0) - Index of the period, default is 0.

        **kwargs** - Additional keyword arguments.

    OUTPUT:
        **index** (int) - The unique ID of the created heat storage controller.

    EXAMPLE:
        create_controlled_heat_storage(prosumer, q_capacity_kwh=10, name="heat_storage_1")
    """

    heat_storage_index = create_heat_storage(
        prosumer,
        **{k: v for k, v in locals().items() if k not in {"prosumer", "period", "order", 'level', 'init_soc', 'kwargs'}},
        **kwargs
    )
    heat_storage_controller_data = HeatStorageControllerData(
        element_name='heat_storage',
        element_index=[heat_storage_index],
        period_index=period
    )
    hs = HeatStorageController(
        prosumer,
        heat_storage_controller_data,
        order=order,
        level=level,
        init_soc=init_soc,
        name=name
    )
    return hs.index


def create_controlled_solar_thermal(prosumer,
                                    collector_area=2.5,
                                    optical_efficiency=0.77,
                                    thermal_losses=3.0,
                                    second_thermal_losses=0.02,
                                    incidence_angle=0.9,
                                    flow_rate=72,
                                    test_specific_heat=4.18,
                                    use_specific_heat=4.18,
                                    number_collectors=4.0,
                                    series=1.0,
                                    piping_length=0.0,
                                    piping_diameter=0.028,
                                    piping_thickness=0.03,
                                    piping_conductivity=0.04,
                                    collector_slope=40.0,
                                    collector_azimut=0.0,
                                    name=None,
                                    index=None,
                                    in_service=True,
                                    level=0,
                                    order=0,
                                    period=0,
                                    **kwargs):

    solar_thermal_index = create_solar_thermal(
        prosumer,
        **{k: v for k, v in locals().items()
           if k not in {"prosumer", "period", "order", "level", "kwargs"}},
        **kwargs
    )

    solar_controller_data = SolarThermalControllerData(
        element_name='solar_thermal',
        element_index=[solar_thermal_index],
        period_index=period,
        **kwargs
    )

    st_controller = SolarThermalController(
        prosumer,
        solar_controller_data,
        order=order,
        level=level,
        name=name
    )

    return st_controller.index


def create_controlled_converter(prosumer, cp_water=4180,
                              name=None,
                              index=None,
                              in_service=True,
                              period=0,
                              level=0,
                              order=0,
                              **kwargs):
    """
    Creates a converter element in prosumer["converter"] and a converter controller.

    INPUT:
        **prosumer** - The prosumer within which this converter should be created.

    OPTIONAL:
        **cp_water** (float) - specific heat capacity, units J/kgK, by default 4180.

        **name** (string, default None) - The name for this chiller.

        **index** (int, default None) - Force a specified ID if it is available. If None, the index one higher than the highest already existing index is selected.

        **in_service** (boolean, default True) - True for in_service or False for out of service.

        **level** (int, default 0) - The level of the controller.

        **order** (int, default 0) - The order of the controller.

        **period** (int, default 0) - Index of the period, default is 0.

    OUTPUT:
        **index** (int) - The unique ID of the created converter.

    EXAMPLE:
        create_controlled_converter(prosumer, "chiller_1")
    """

    converter_index = create_converter(
        prosumer,
        **{k: v for k, v in locals().items() if k not in {"prosumer", "period", "order", "level", "kwargs"}},
        **kwargs)

    converter_controller_data = ConverterControllerData(
        element_name='converter',
        element_index=[converter_index],
        period_index=period,
        **kwargs
    )

    converter_controller = GenericToFluidMixController(prosumer,
                                                       converter_controller_data,
                                                       order=order,
                                                       level=level,
                                                       name=name,
                                                       index=index,
                                                       in_service=in_service,
                                                      )
    return converter_controller.index
  
  
def create_controlled_senergy_nets_pv_production(
    prosumer,
    latitude,
    longitude,
    raddatabase="PVGIS-ERA5",
    surface_tilt=40,
    surface_azimuth=0,
    loss=0,
    usehorizon=True,
    userhorizon=None,
    peakpower=1,
    pvtechchoice="crystSi",
    mountingplace="free",
    trackingtype=0,
    optimal_surface_tilt=False,
    optimalangles=False,
    outputformat="json",
    url="https://re.jrc.ec.europa.eu/api/v5_2/seriescalc?",
    map_variables=True,
    timeout=30,
    name=None,
    index=None,
    in_service=True,
    level=0,
    order=0,
    period=0,
    **kwargs
):
    """
    Creates a controlled Senergy Nets PV production component, adds it to the
    prosumer model, and links it to a PV production controller.

    Parameters
    ----------
    prosumer : object
        The prosumer container to which the PV production unit will be added.
    latitude : float
        Latitude of the PV installation.
    longitude : float
        Longitude of the PV installation.
    raddatabase : str, optional
        Radiation database source, by default 'PVGIS-ERA5'.
    surface_tilt : float, optional
        Tilt angle of the PV surface (degrees), by default 40.
    surface_azimuth : float, optional
        Azimuth of the PV surface (degrees), by default 0.
    loss : float, optional
        System losses (%), by default 0.
    usehorizon : bool, optional
        Whether to use horizon data, by default True.
    userhorizon : float or None, optional
        User-defined horizon, by default None.
    peakpower : float, optional
        Installed PV peak power (kWp), by default 1.
    pvtechchoice : str, optional
        PV technology type, by default 'crystSi'.
    mountingplace : str, optional
        Mounting type, by default 'free'.
    trackingtype : int, optional
        PV tracking type, by default 0.
    optimal_surface_tilt : bool, optional
        Whether to use optimal surface tilt, by default False.
    optimalangles : bool, optional
        Whether to optimize surface angles, by default False.
    outputformat : str, optional
        API output format, by default 'json'.
    url : str, optional
        PVGIS API endpoint, by default given URL.
    map_variables : bool, optional
        Map output variables to internal names, by default True.
    timeout : int, optional
        API timeout (s), by default 30.
    in_service : bool, optional
        Whether the unit is active, by default True.
    name : str, optional
        Optional name of the element, by default None.
    level : int, optional
        Hierarchy level for controller, by default 0.
    order : int, optional
        Execution order of controller, by default 0.
    period : int, optional
        Period index for time-based operation, by default 0.

    Returns
    -------
    int
        Controller index of the created PV production controller.
    """

    pv_index = create_senergy_nets_pv_production(
        prosumer,
        **{k: v for k, v in locals().items()
           if k not in {"prosumer", "period", "order", "level", "kwargs"}},
        **kwargs
    )

    pv_controller_data = SenergyNetsPvProductionComponentData(
        element_name='sn_pv_production',
        element_index=[pv_index],
        period_index=period,
        **kwargs
    )

    pv_controller = SenergyNetsPvProductionController(
        prosumer,
        pv_controller_data,
        order=order,
        level=level,
        name=name
    )

    return pv_controller.index
  

def create_controlled_senergy_nets_pv_production(
    prosumer,
    latitude,
    longitude,
    raddatabase="PVGIS-ERA5",
    surface_tilt=40,
    surface_azimuth=0,
    loss=0,
    usehorizon=True,
    userhorizon=None,
    peakpower=1,
    pvtechchoice="crystSi",
    mountingplace="free",
    trackingtype=0,
    optimal_surface_tilt=False,
    optimalangles=False,
    outputformat="json",
    url="https://re.jrc.ec.europa.eu/api/v5_2/seriescalc?",
    map_variables=True,
    timeout=30,
    name=None,
    index=None,
    in_service=True,
    level=0,
    order=0,
    period=0,
    **kwargs
):
    """
    Creates a controlled Senergy Nets PV production component, adds it to the
    prosumer model, and links it to a PV production controller.

    Parameters
    ----------
    prosumer : object
        The prosumer container to which the PV production unit will be added.
    latitude : float
        Latitude of the PV installation.
    longitude : float
        Longitude of the PV installation.
    raddatabase : str, optional
        Radiation database source, by default 'PVGIS-ERA5'.
    surface_tilt : float, optional
        Tilt angle of the PV surface (degrees), by default 40.
    surface_azimuth : float, optional
        Azimuth of the PV surface (degrees), by default 0.
    loss : float, optional
        System losses (%), by default 0.
    usehorizon : bool, optional
        Whether to use horizon data, by default True.
    userhorizon : float or None, optional
        User-defined horizon, by default None.
    peakpower : float, optional
        Installed PV peak power (kWp), by default 1.
    pvtechchoice : str, optional
        PV technology type, by default 'crystSi'.
    mountingplace : str, optional
        Mounting type, by default 'free'.
    trackingtype : int, optional
        PV tracking type, by default 0.
    optimal_surface_tilt : bool, optional
        Whether to use optimal surface tilt, by default False.
    optimalangles : bool, optional
        Whether to optimize surface angles, by default False.
    outputformat : str, optional
        API output format, by default 'json'.
    url : str, optional
        PVGIS API endpoint, by default given URL.
    map_variables : bool, optional
        Map output variables to internal names, by default True.
    timeout : int, optional
        API timeout (s), by default 30.
    in_service : bool, optional
        Whether the unit is active, by default True.
    name : str, optional
        Optional name of the element, by default None.
    level : int, optional
        Hierarchy level for controller, by default 0.
    order : int, optional
        Execution order of controller, by default 0.
    period : int, optional
        Period index for time-based operation, by default 0.

    Returns
    -------
    int
        Controller index of the created PV production controller.
    """

    pv_index = create_senergy_nets_pv_production(
        prosumer,
        **{k: v for k, v in locals().items()
           if k not in {"prosumer", "period", "order", "level", "kwargs"}},
        **kwargs
    )

    pv_controller_data = SenergyNetsPvProductionComponentData(
        element_name='sn_pv_production',
        element_index=[pv_index],
        period_index=period,
        **kwargs
    )

    pv_controller = SenergyNetsPvProductionController(
        prosumer,
        pv_controller_data,
        order=order,
        level=level,
        name=name
    )

    return pv_controller.index

def create_controlled_mdu_chp(prosumer,
                               size,
                               name=None,
                               index=None,
                               in_service=True,
                               level=0,
                               order=0,
                               period=0,
                               **kwargs):
    """
    Creates an MDU CHP element in prosumer["mdu_chp"] and an MDU CHP controller

    INPUT:
        **prosumer** - The prosumer within which this MDU CHP should be created

        **size** (float) - MDU CHP size defined as the nominal electrical power [kW]

    OPTIONAL:
        **name** (string, default None) - The name of the MDU CHP instance

        **index** (int, default None) - Force a specified ID if it is available. If None, the index one \
            higher than the highest already existing index is selected.

        **in_service** (boolean, default True) - True for in_service or False for out of service

        **level** (int, default 0) - The level of the controller

        **order** (int, default 0) - The order of the controller

        **period** (int, default 0) - Index of the period, default is 0

    OUTPUT:
        **index** (int) - The unique ID of the created MDU CHP controller

    EXAMPLE:
        create_controlled_mdu_chp(prosumer, 100, name="example_mdu_chp")
    """
    mdu_chp_index = create_mdu_chp(prosumer, size, in_service, name, index, **kwargs)
    mdu_chp_controller_data = MduChpControllerData(
        element_name='mdu_chp',
        element_index=[mdu_chp_index],
        period_index=period
    )
    mdu_chp = MduChpController(prosumer,
                               mdu_chp_controller_data,
                               order=order,
                               level=level,
                               in_service=in_service,
                               index=None,
                               name=name)
    return mdu_chp.index
