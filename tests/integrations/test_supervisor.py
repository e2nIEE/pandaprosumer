from pandaprosumer.mapping import GenericMapping
from pandaprosumer.supervisor.supervisor import *
from pandaprosumer import *
import numpy as np
import pytest
import re
from pandaprosumer.run_time_series import run_timeseries

def _define_and_get_period_and_data_source(prosumer):
    data = pd.DataFrame({"price_gas": [15, 26, 26, 30],
                         "Tin_evap": [25, 25, 25, 25],
                         "demand_1": [50, 200, 800, 300]})

    start = '2020-01-01 00:00:00'
    resol = 3600
    end = pd.Timestamp(start) + len(data["price_gas"]) * pd.Timedelta(f"00:00:{resol}") - pd.Timedelta("00:00:01")
    dur = pd.date_range(start, end, freq='%ss' % resol, tz='utc')
    period = create_period(prosumer,
                           resol,
                           start,
                           end,
                           'utc',
                           'default')

    data.index = dur
    data_source = DFData(data)


    return period, data_source

def create_controllers(prosumer,period):
    hp_params = {'carnot_efficiency': 0.5,
                 'pinch_c': 0,
                 'delta_t_evap_c': 5,
                 'max_p_comp_kw': 100}

    gb_params = {'max_q_kw': 500}

    hd_params = {'t_in_set_c': 76.85, 't_out_set_c': 30}

    gb_index = create_controlled_gas_boiler(prosumer, period=period, order=0, level=2, **gb_params)
    hp_index = create_controlled_heat_pump(prosumer, period=period, order=1, level=2, **hp_params)
    hd_index = create_controlled_heat_demand(prosumer, period=period, order=2, level=2, **hd_params)

    return hp_index, gb_index, hd_index

def mapping_controller(prosumer,supervisor,cp,hp_index,gb_index,hd_index):

    GenericMapping(prosumer,
                    initiator_id=cp,
                    initiator_column='price_gas',
                    responder_id=supervisor,
                    responder_column='price_gas',
                    order=0)

    GenericMapping(container=prosumer,
                   initiator_id=cp,
                   initiator_column="t_evap_in_c",
                   responder_id=hp_index,
                   responder_column="t_evap_in_c",
                   order=1)


    GenericMapping(container=prosumer,
               initiator_id=cp,
               initiator_column="q_demand_kw",
               responder_id=hd_index,
               responder_column="q_demand_kw",
               order=2)

    FluidMixMapping(container=prosumer,
                initiator_id=hp_index,
                responder_id=hd_index,
                order=0)

    FluidMixMapping(container=prosumer,
                initiator_id=gb_index,
                responder_id=hd_index,
                order=0)

class TestSupervisor:

    def test_create_supervisor(self):
        prosumer = create_empty_prosumer_container()
        create_controlled_supervisor(prosumer, input_columns=[])
        assert hasattr(prosumer, "controller")
        assert len(prosumer.controller) == 1

    def test_modify_in_service(self):

        prosumer = create_empty_prosumer_container()
        period, data_source = _define_and_get_period_and_data_source(prosumer)

        input_columns = ['price_gas', 'Tin_evap', 'demand_1']
        result_columns = ['price_gas', 't_evap_in_c', 'q_demand_kw']

        cp = create_controlled_const_profile(prosumer,period=period,data_source = data_source,
                                             input_columns=input_columns,result_columns=result_columns,
                                             order = 0,level = 0)

        supervisor_index = create_controlled_supervisor(prosumer,input_columns = ['price_gas'],period = period, level = 1 , order = 0)
        supervisor = prosumer.controller.iloc[supervisor_index].object
        hp_index, gb_index, hd_index = create_controllers(prosumer,period)

        rule1 = Rule(controlled_columns='price_gas',operator_str='>',threshold_value=28,controller=gb_index,attr = 'in_service',new_value = False, value_if_false=True)
        rule2 = Rule(controlled_columns='price_gas',operator_str='>',threshold_value=28,controller=hp_index,attr = 'in_service',new_value = True, value_if_false=False)

        supervisor.add_rule(rule1)
        supervisor.add_rule(rule2)

        mapping_controller(prosumer,supervisor_index,cp,hp_index,gb_index,hd_index)

        run_timeseries(prosumer, period, True)
        expected_values_qw = [50.0, 200.0, 500.0, 0.]
        expected_values_q_cond_kw = [0.0,0.,0.,300.]
        q_received_kw = [50.0, 200.0, 500.0,300.]

        assert prosumer.time_series.loc[0, 'data_source'].df.q_kw.values.tolist() == expected_values_qw
        assert prosumer.time_series.loc[1, 'data_source'].df.q_cond_kw.values.tolist() == expected_values_q_cond_kw
        assert np.allclose(prosumer.time_series.loc[2, 'data_source'].df.q_received_kw.values.tolist(), q_received_kw, atol=1)

    def test_modify_order(self):
        prosumer = create_empty_prosumer_container()
        period, data_source = _define_and_get_period_and_data_source(prosumer)

        input_columns = ['price_gas', 'Tin_evap', 'demand_1']
        result_columns = ['price_gas', 't_evap_in_c', 'q_demand_kw']
        cp = create_controlled_const_profile(prosumer, period=period, data_source=data_source,
                                             input_columns=input_columns, result_columns=result_columns,
                                             order=0, level=0)

        supervisor_index = create_controlled_supervisor(prosumer, input_columns=['price_gas'], period=period, level=1,
                                                        order=0)
        supervisor = prosumer.controller.iloc[supervisor_index].object
        hp_index, gb_index, hd_index = create_controllers(prosumer, period)

        rule1 = Rule(controlled_columns='price_gas', operator_str='>', threshold_value=28, controller=gb_index, attr='order', new_value=1, value_if_false=0)
        rule2 = Rule(controlled_columns='price_gas', operator_str='>', threshold_value=28, controller=hp_index, attr='order', new_value=0, value_if_false=1)

        supervisor.add_rule(rule1)
        supervisor.add_rule(rule2)

        mapping_controller(prosumer, supervisor_index, cp, hp_index, gb_index, hd_index)

        run_timeseries(prosumer, period, True)
        expected_values_qw = [50.0, 200.0, 500.0, 0.]
        expected_values_q_cond_kw = [0.0, 0., 0., 300.]
        q_received_kw = [50.0, 200.0, 500.0, 300.]

        assert prosumer.time_series.loc[0, 'data_source'].df.q_kw.values.tolist() == expected_values_qw
        assert prosumer.time_series.loc[1, 'data_source'].df.q_cond_kw.values.tolist() == expected_values_q_cond_kw
        assert np.allclose(prosumer.time_series.loc[2, 'data_source'].df.q_received_kw.values.tolist(),
                           q_received_kw, atol=1)

    def test_modify_max_value(self):

        prosumer = create_empty_prosumer_container()
        period, data_source = _define_and_get_period_and_data_source(prosumer)

        input_columns = ['price_gas', 'Tin_evap', 'demand_1']
        result_columns = ['price_gas', 't_evap_in_c', 'q_demand_kw']

        cp = create_controlled_const_profile(prosumer,period=period,data_source = data_source,
                                             input_columns=input_columns,result_columns=result_columns,
                                             order = 0,level = 0)

        supervisor_index = create_controlled_supervisor(prosumer,input_columns = ['price_gas'],period = period, level = 1 , order = 0)
        supervisor = prosumer.controller.iloc[supervisor_index].object
        hp_index, gb_index, hd_index = create_controllers(prosumer,period)
        rule1 = Rule('price_gas','==',25,gb_index,'max_q_kw',200)
        rule2 = Rule('price_gas','>',25,gb_index,'max_q_kw',300)
        supervisor.add_rule(rule1)
        supervisor.add_rule(rule2)
        mapping_controller(prosumer, supervisor_index, cp, hp_index, gb_index, hd_index)
        run_timeseries(prosumer, period, True)
        expected_values = [50.0,200.0,300.0,300.0]
        assert prosumer.time_series.loc[0,'data_source'].df.q_kw.values.tolist() == expected_values

    def test_exceed_max_value(self):
        prosumer = create_empty_prosumer_container()
        period, data_source = _define_and_get_period_and_data_source(prosumer)
        input_columns = ['price_gas', 'Tin_evap', 'demand_1']
        result_columns = ['price_gas', 't_evap_in_c', 'q_demand_kw']
        cp = create_controlled_const_profile(prosumer, period=period, data_source=data_source,
                                             input_columns=input_columns, result_columns=result_columns,
                                             order=0, level=0)
        supervisor_index = create_controlled_supervisor(prosumer,input_columns = ['price_gas'],period = period, level = 1 , order = 0)
        supervisor = prosumer.controller.iloc[supervisor_index].object
        hp_index, gb_index, hd_index = create_controllers(prosumer, period)
        rule_forbidden = Rule('price_gas', '>', 0, gb_index, 'max_q_kw', 800)
        supervisor.add_rule(rule_forbidden)
        mapping_controller(prosumer, supervisor_index, cp, hp_index, gb_index, hd_index)
        with pytest.raises(ValueError, match=re.escape(
                "The new value 800 should not exceed the original max_q_kw value (500.0).")):
            run_timeseries(prosumer, period, True)


    def test_supervised_heat_pump(self):
        prosumer = create_empty_prosumer_container()
        period, data_source = _define_and_get_period_and_data_source(prosumer)
        input_columns = ['price_gas','Tin_evap', 'demand_1']
        result_columns = ['price_gas', 't_evap_in_c','q_demand_kw']

        cp = create_controlled_const_profile(prosumer, period=period, data_source=data_source,
                                             input_columns=input_columns, result_columns=result_columns,
                                             order=0, level=0)

        supervisor_index = create_controlled_supervisor(prosumer, input_columns=['p_comp_kw'], period=period, level=2, order=0)
        supervisor = prosumer.controller.iloc[supervisor_index].object

        hp_params = {'carnot_efficiency': 0.5,
                     'pinch_c': 0,
                     'delta_t_evap_c': 5,
                     'max_p_comp_kw': 400}

        gb_params = {'max_q_kw': 500}

        hd_params = {'t_in_set_c': 76.85, 't_out_set_c': 30}

        gb_index = create_controlled_gas_boiler(prosumer, period=period, order=1, level=1, **gb_params)
        hp_index = create_controlled_heat_pump(prosumer, period=period, order=0, level=1, **hp_params)
        hd_index = create_controlled_heat_demand(prosumer, period=period, order=2, level=1, **hd_params)

        rule = Rule('p_comp_kw','>',200,hp_index,'order',1)
        supervisor.add_rule(rule)
        rule = Rule('p_comp_kw','>',200,gb_index,'order',0)
        supervisor.add_rule(rule)

        GenericMapping(container=prosumer,
                       initiator_id=cp,
                       initiator_column="t_evap_in_c",
                       responder_id=hp_index,
                       responder_column="t_evap_in_c",
                       order=0)

        GenericMapping(container=prosumer,
                       initiator_id=hp_index,
                       initiator_column='p_comp_kw',
                       responder_id=supervisor_index,
                       responder_column='p_comp_kw',
                       order=1)

        GenericMapping(container=prosumer,
                       initiator_id=cp,
                       initiator_column="q_demand_kw",
                       responder_id=hd_index,
                       responder_column="q_demand_kw",
                       order=2)

        FluidMixMapping(container=prosumer,
                        initiator_id=hp_index,
                        responder_id=hd_index,
                        order=0)

        FluidMixMapping(container=prosumer,
                        initiator_id=gb_index,
                        responder_id=hd_index,
                        order=0)
        run_timeseries(prosumer, period, True)

        expected_values_q_kw = [0.0, 0.0, 0.0, 300]
        expected_value_p_comp_kw = [14, 59, 237, 0]

        assert prosumer.time_series.loc[1, 'data_source'].df.q_kw.values.tolist() == expected_values_q_kw
        assert [int(x) for x in
                prosumer.time_series.loc[0, 'data_source'].df.p_comp_kw.values.tolist()] == expected_value_p_comp_kw


    def test_combining_rules0(self):
        prosumer = create_empty_prosumer_container()
        period, data_source = _define_and_get_period_and_data_source(prosumer)
        input_columns = ['price_gas', 'Tin_evap', 'demand_1']
        result_columns = ['price_gas', 't_evap_in_c', 'q_demand_kw']

        cp = create_controlled_const_profile(prosumer, period=period, data_source=data_source,
                                             input_columns=input_columns, result_columns=result_columns,
                                             order=0, level=0)

        supervisor_index = create_controlled_supervisor(prosumer, input_columns=['price_gas','p_comp_kw'], period=period, level=2, order=0)
        supervisor = prosumer.controller.iloc[supervisor_index].object

        hp_params = {'carnot_efficiency': 0.5,
                     'pinch_c': 0,
                     'delta_t_evap_c': 5,
                     'max_p_comp_kw': 400}

        gb_params = {'max_q_kw': 500}

        hd_params = {'t_in_set_c': 76.85, 't_out_set_c': 30}

        gb_index = create_controlled_gas_boiler(prosumer, period=period, order=1, level=1, **gb_params)
        hp_index = create_controlled_heat_pump(prosumer, period=period, order=0, level=1, **hp_params)
        hd_index = create_controlled_heat_demand(prosumer, period=period, order=2, level=1, **hd_params)

        rule1 = Rule('p_comp_kw', '>', 200, gb_index, 'order', 0, value_if_false=1)
        rule2 = Rule('price_gas', '>', 20, hp_index, 'order', 1, value_if_false=0)
        rule2_ = Rule('q_demand_kw', '<', 100, hp_index, 'order', 1, value_if_false=0)
        supervisor.add_rule(CombiningRules([rule1, rule2, rule2_], 'AND'))
        rule3 = Rule('p_comp_kw', '>', 500, hp_index, 'in_service', False, value_if_false=True)
        supervisor.add_rule(rule3)
        print(prosumer['Rules'])

        rules_df = prosumer['Rules']


        expected_rule_count = 4  # rule1, rule2, rule2_, rule3
        assert len(rules_df) == expected_rule_count

        print(rules_df['controlled_columns'])
        assert set(rules_df['controlled_columns']) == {'p_comp_kw', 'price_gas', 'q_demand_kw'}

        combining_rule_index = rules_df[rules_df['logical_operator'] == 'AND'].index
        assert len(combining_rule_index) == 3
        combining_rule_row = rules_df.loc[combining_rule_index[0]]
        linked_rules = combining_rule_row['linked_rules']
        assert len(linked_rules) == 2


    def test_combining_rules1(self):
        prosumer = create_empty_prosumer_container()
        period, data_source = _define_and_get_period_and_data_source(prosumer)
        input_columns = ['price_gas', 'Tin_evap', 'demand_1']
        result_columns = ['price_gas', 't_evap_in_c', 'q_demand_kw']

        cp = create_controlled_const_profile(prosumer, period=period, data_source=data_source,
                                             input_columns=input_columns, result_columns=result_columns,
                                             order=0, level=0)

        supervisor_index = create_controlled_supervisor(prosumer, input_columns=['price_gas','p_comp_kw'], period=period, level=2, order=0)
        supervisor = prosumer.controller.iloc[supervisor_index].object

        hp_params = {'carnot_efficiency': 0.5,
                     'pinch_c': 0,
                     'delta_t_evap_c': 5,
                     'max_p_comp_kw': 400}

        gb_params = {'max_q_kw': 500}

        hd_params = {'t_in_set_c': 76.85, 't_out_set_c': 30}

        gb_index = create_controlled_gas_boiler(prosumer, period=period, order=1, level=1, **gb_params)
        hp_index = create_controlled_heat_pump(prosumer, period=period, order=0, level=1, **hp_params)
        hd_index = create_controlled_heat_demand(prosumer, period=period, order=2, level=1, **hd_params)

        rule1 = Rule('p_comp_kw', '>', 200, gb_index, 'order', 0, value_if_false=1)
        rule2 = Rule('price_gas', '>', 20, hp_index, 'order', 1, value_if_false=0)
        supervisor.add_rule(CombiningRules([rule1, rule2], 'AND'))

        GenericMapping(container=prosumer,
                       initiator_id=cp,
                       initiator_column="t_evap_in_c",
                       responder_id=hp_index,
                       responder_column="t_evap_in_c",
                       order=0)

        GenericMapping(container=prosumer,
                       initiator_id=cp,
                       initiator_column="price_gas",
                       responder_id=supervisor_index,
                       responder_column="price_gas",
                       order=1)

        GenericMapping(container=prosumer,
                       initiator_id=hp_index,
                       initiator_column='p_comp_kw',
                       responder_id=supervisor_index,
                       responder_column='p_comp_kw',
                       order=0)

        GenericMapping(container=prosumer,
                       initiator_id=cp,
                       initiator_column="q_demand_kw",
                       responder_id=hd_index,
                       responder_column="q_demand_kw",
                       order=2)

        FluidMixMapping(container=prosumer,
                        initiator_id=hp_index,
                        responder_id=hd_index,
                        order=0)

        FluidMixMapping(container=prosumer,
                        initiator_id=gb_index,
                        responder_id=hd_index,
                        order=0)
        run_timeseries(prosumer, period, True)

        expected_values_q_kw = [0.0,0.0,0.0,300]
        expected_value_p_comp_kw = [14,59,237,0]

        assert prosumer.time_series.loc[1, 'data_source'].df.q_kw.values.tolist() == expected_values_q_kw
        assert [int(x) for x in prosumer.time_series.loc[0, 'data_source'].df.p_comp_kw.values.tolist()] == expected_value_p_comp_kw

    def test_mapping_order(self):
        prosumer = create_empty_prosumer_container()
        max_hp_qcond = 337.512054
        data = pd.DataFrame({"Tin_evap": [25., 25., 25.,25.,25.],
                             "demand_1": [50., 200., max_hp_qcond + 30.,300,400],
                             "demand_2": [100., max_hp_qcond - 200 + 40., 70.,400,300],
                             "dummy_rule": [0, 0, 0, 1, 1]})

        start = '2020-01-01 00:00:00'
        resol = 3600
        end = pd.Timestamp(start) + len(data["Tin_evap"]) * pd.Timedelta(f"00:00:{resol}") - pd.Timedelta("00:00:01")
        dur = pd.date_range(start, end, freq='%ss' % resol, tz='utc')
        period = create_period(prosumer,
                               resol,
                               start,
                               end,
                               'utc',
                               'default')

        data.index = dur
        data_source = DFData(data)

        cp_input_columns = ["Tin_evap", "demand_1", "demand_2","dummy_rule"]
        cp_result_columns = ["t_evap_in_c", "qdemand1_kw", "qdemand2_kw","dummy_rule"]
        hp_params = {'carnot_efficiency': 0.5,
                     'pinch_c': 0,
                     'delta_t_evap_c': 5,
                     'max_p_comp_kw': 100}
        hd_params = {'t_in_set_c': 76.85, 't_out_set_c': 30}
        cp_controller_index = create_controlled_const_profile(prosumer, cp_input_columns, cp_result_columns,
                                                              data_source=data_source,period = period,level = 0,order = 0)
        supervisor_index = create_controlled_supervisor(prosumer, input_columns=['dummy_rule'], period=period, level=1, order=0)
        supervisor = prosumer.controller.iloc[supervisor_index].object
        hp_controller_index = create_controlled_heat_pump(prosumer, period=period, level=2, order=0, **hp_params)
        hd_controller_index_1 = create_controlled_heat_demand(prosumer, period=period, level=2, order=1, **hd_params)
        hd_controller_index_2 = create_controlled_heat_demand(prosumer, period=period, level=2, order=2, **hd_params)

        GenericMapping(container=prosumer,
                       initiator_id=cp_controller_index,
                       initiator_column="t_evap_in_c",
                       responder_id=hp_controller_index,
                       responder_column="t_evap_in_c",
                       order=0)

        GenericMapping(container=prosumer,
                       initiator_id=cp_controller_index,
                       initiator_column="qdemand1_kw",
                       responder_id=hd_controller_index_1,
                       responder_column="q_demand_kw",
                       order=1)

        GenericMapping(container=prosumer,
                       initiator_id=cp_controller_index,
                       initiator_column="qdemand2_kw",
                       responder_id=hd_controller_index_2,
                       responder_column="q_demand_kw",
                       order=2)

        GenericMapping(container=prosumer,
                       initiator_id=cp_controller_index,
                       initiator_column="dummy_rule",
                       responder_id=supervisor_index,
                       responder_column="dummy_rule",
                       order = 3)

        first_mapping = FluidMixMapping(container=prosumer,
                        initiator_id=hp_controller_index,
                        responder_id=hd_controller_index_1,
                        order=0)

        second_mapping = FluidMixMapping(container=prosumer,
                        initiator_id=hp_controller_index,
                        responder_id=hd_controller_index_2,
                        order=1)

        rule1 = Rule('dummy_rule', '==', 0, first_mapping.index, 'order', 0, value_if_false=1, mapping = True)
        rule2 = Rule('dummy_rule', '==', 1, second_mapping.index, 'order', 0, value_if_false=1, mapping = True)
        supervisor.add_rule(rule1)
        supervisor.add_rule(rule2)

        run_timeseries(prosumer, period, True)

        expected_values = [50.,200.,max_hp_qcond,0.,max_hp_qcond-300.]
        actual_values = prosumer.time_series.loc[1, 'data_source'].df.q_received_kw.values.tolist()

        rounded_actual = np.round(actual_values, 3).tolist()
        rounded_expected = np.round(expected_values, 3).tolist()

        assert rounded_actual == rounded_expected