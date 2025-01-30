from pandaprosumer.create import *
from pandaprosumer.controller import *


def init_const_profile_controller(prosumer, input_columns, result_columns, period, data_source, level=0, order=0):
    const_controller_data = ConstProfileControllerData(
        input_columns=input_columns,
        result_columns=result_columns,
        # period_index=period,
    )
    ConstProfileController(prosumer,
                           const_object=const_controller_data,
                           df_data=data_source,
                           order=order,
                           level=level)
    return prosumer.controller.index[-1]


def init_hp_element(prosumer, **kwargs):
    default = {'max_p_comp_kw': 500,
               'min_p_comp_kw': .01,
               'max_t_cond_out_c': 100,
               'max_cop': 10,
               'pinch_c': 0
               }
    default.update(kwargs)
    heat_pump_index = create_heat_pump(
        prosumer,
        **default
    )
    return heat_pump_index


def init_hp_controller(prosumer, period_index, elements_indexes, level=0, order=0, **kwargs):
    heat_pump_controller_data = HeatPumpControllerData(
        element_name='heat_pump',
        element_index=elements_indexes,
        period_index=period_index,
        **kwargs
    )
    HeatPumpController(prosumer,
                       heat_pump_controller_data,
                       order=order,
                       level=level,
                       name='heat_pump_controller')
    return prosumer.controller.index[-1]


def init_hd_element(prosumer, **kwargs):
    default = {'t_in_set_c': 76.85,
               't_out_set_c': 30}
    default.update(kwargs)
    heat_demand_index = create_heat_demand(prosumer, **default)
    return heat_demand_index


def init_hd_controller(prosumer, period_index, elements_indexes, level=0, order=0, **kwargs):
    heat_demand_controller_data = HeatDemandControllerData(
        element_name='heat_demand',
        element_index=elements_indexes,
        period_index=period_index,
        **kwargs
    )
    HeatDemandController(prosumer,
                         heat_demand_controller_data,
                         order=order,
                         level=level,
                         name='heat_demand_controller')
    return prosumer.controller.index[-1]


def init_shs_element(prosumer, **kwargs):
    default = {'tank_height_m': 12, 'tank_internal_radius_m': 4.}
    default.update(kwargs)
    stratified_heat_storage_index = create_stratified_heat_storage(
        prosumer,
        **default
    )
    return stratified_heat_storage_index


def init_shs_controller(prosumer, period, elements_indexes, level=0, order=0, init_layer_temps_c=None, plot=False, **kwargs):
    stratified_heat_storage_controller_data = StratifiedHeatStorageControllerData(
        element_name='stratified_heat_storage',
        element_index=elements_indexes,
        period_index=period,
        **kwargs
    )
    StratifiedHeatStorageController(prosumer,
                                    stratified_heat_storage_controller_data,
                                    order=order,
                                    level=level,
                                    init_layer_temps_c=init_layer_temps_c,
                                    plot=plot,
                                    name='stratified_heat_storage_controller')
    return prosumer.controller.index[-1]


def init_hx_element(prosumer, **kwargs):
    heat_exchanger_index = create_heat_exchanger(
        prosumer,
        **kwargs
    )
    return heat_exchanger_index


def init_hx_controller(prosumer, period, elements_indexes, level=0, order=0, **kwargs):
    heat_exchanger_controller_data = HeatExchangerControllerData(
        element_name='heat_exchanger',
        element_index=elements_indexes,
        period_index=period,
        **kwargs
    )
    HeatExchangerController(prosumer,
                            heat_exchanger_controller_data,
                            order=order,
                            level=level,
                            name='heat_exchanger_controller')
    return prosumer.controller.index[-1]


def init_dc_element(prosumer, **kwargs):
    default = {'n_nom_rpm': 730,
               'p_fan_nom_kw': 9.38,
               'qair_nom_m3_per_h': 138200}
    default.update(kwargs)
    dry_cooler_index = create_dry_cooler(
        prosumer,
        **default
    )
    return dry_cooler_index


def init_dc_controller(prosumer, period, elements_indexes, level=0, order=0, **kwargs):
    dry_cooler_controller_data = DryCoolerControllerData(
        element_name='dry_cooler',
        element_index=elements_indexes,
        period_index=period,
        **kwargs
    )
    DryCoolerController(prosumer,
                        dry_cooler_controller_data,
                        order=order,
                        level=level,
                        name='dry_cooler_controller')
    return prosumer.controller.index[-1]


def init_elb_element(prosumer, **kwargs):
    default = {'max_p_kw': 100}
    default.update(kwargs)
    electric_boiler_index = create_electric_boiler(
        prosumer,
        **default
    )
    return electric_boiler_index


def init_elb_controller(prosumer, period, elements_indexes, level=0, order=0, **kwargs):
    dry_cooler_controller_data = ElectricBoilerControllerData(
        element_name='electric_boiler',
        element_index=elements_indexes,
        period_index=period,
        **kwargs
    )
    ElectricBoilerController(prosumer,
                             dry_cooler_controller_data,
                             order=order,
                             level=level,
                             name='electric_boiler_controller')
    return prosumer.controller.index[-1]
