import pytest

from pandaprosumer.mapping import GenericMapping
from pandaprosumer.tests.integrations.base_controller import BaseControllerData

from pandaprosumer import *
from pandaprosumer.tests.data_sources.define_period import define_and_get_period_and_data_source


def _init_dummy_controller(prosumer, input_columns, result_columns, level=0, order=0, **kwargs):
    dummy_controller_data = BaseControllerData(
        input_columns=input_columns,
        result_columns=result_columns
    )
    BasicProsumerController(prosumer,
                            dummy_controller_data,
                            order=order,
                            level=level)
    return prosumer.controller.index[-1]


class TestMapping:
    """
    Create some controllers and mapping
    Overwrite the t_m_to_deliver function of the downstream controllers so they act as heat demands
    Check the resulting t_m_to_deliver and t_m_to_receive of the upstream controllers
    """

    def _map(self, prosumer, initiator):
        """
        Run the mappings in 'prosumer' for which 'initiator' is the initiator controller
        """
        for row in initiator._get_mappings(prosumer):
            if row.object.responder_net == prosumer:
                row.object.map(initiator, prosumer.controller.loc[row.responder].object)

    def test_create_fluidmix_mapping(self):
        """
        Create some controllers and mapping
        Overwrite the t_m_to_deliver function of the downstream controllers so they act as heat demands
        Check the resulting t_m_to_deliver and t_m_to_receive of the upstream controllers
        """
        prosumer = create_empty_prosumer_container()
        period, data_source = define_and_get_period_and_data_source(prosumer)

        dummy_controller_index = _init_dummy_controller(prosumer, [], ['ctrl_out', 'ctrl_out2'])
        dummy_controller_index2 = _init_dummy_controller(prosumer, ['ctrl_in'], [])

        dummy_controller = prosumer.controller.loc[dummy_controller_index, 'object']
        dummy_controller2 = prosumer.controller.loc[dummy_controller_index2, 'object']

        assert len(prosumer.controller) == 2
        assert len(dummy_controller._get_mapped_responders(prosumer)) == 0
        assert len(dummy_controller2._get_mapped_responders(prosumer)) == 0
        assert len(dummy_controller._get_mapped_responders(prosumer, remove_duplicate=False)) == 0
        assert len(dummy_controller._get_mappings(prosumer)) == 0
        assert len(dummy_controller2._get_mappings(prosumer)) == 0
        assert dummy_controller2.t_m_to_deliver(prosumer) == pytest.approx((0, 0, np.array([])))
        assert dummy_controller2.t_m_to_receive(prosumer) == pytest.approx((0, 0, 0))

        dummy_controller2.t_m_to_deliver = lambda container: (100, 30.5, np.array([1, 5.2, 0.3]))
        assert dummy_controller2.t_m_to_deliver(prosumer)[0] == pytest.approx(100)
        assert dummy_controller2.t_m_to_deliver(prosumer)[1] == pytest.approx(30.5)
        assert dummy_controller2.t_m_to_deliver(prosumer)[2] == pytest.approx(np.array([1, 5.2, .3]))
        assert dummy_controller2.t_m_to_receive(prosumer) == pytest.approx((100, 30.5, 6.5))

        FluidMixMapping(container=prosumer,
                        initiator_id=dummy_controller_index,
                        responder_id=dummy_controller_index2,
                        order=0)

        assert len(dummy_controller._get_mappings(prosumer)) == 1
        assert len(dummy_controller2._get_mappings(prosumer)) == 0

    def test_fluidmix_order(self):
        """
        Check that controller._get_mappings(prosumer) return the mapping in the good order
        """
        prosumer = create_empty_prosumer_container()
        period, data_source = define_and_get_period_and_data_source(prosumer)

        initiator_controller_index = _init_dummy_controller(prosumer, [], ['ctrl_out', 'ctrl_out2'])
        responder_controller_index = _init_dummy_controller(prosumer, ['ctrl_in'], [])

        initiator_controller = prosumer.controller.loc[initiator_controller_index, 'object']
        responder_controller = prosumer.controller.loc[responder_controller_index, 'object']

        first_mapping = FluidMixMapping(container=prosumer,
                                        initiator_id=initiator_controller_index,
                                        responder_id=responder_controller_index,
                                        order=0)

        second_mapping = FluidMixMapping(container=prosumer,
                                         initiator_id=initiator_controller_index,
                                         responder_id=responder_controller_index,
                                         order=1)

        assert initiator_controller._get_mappings(prosumer)[0].object == first_mapping
        assert initiator_controller._get_mappings(prosumer)[1].object == second_mapping

    def test_fluidmix_order_reverse(self):
        """
        Check that controller._get_mappings(prosumer) return the mapping in the good order
        """
        prosumer = create_empty_prosumer_container()
        period, data_source = define_and_get_period_and_data_source(prosumer)

        initiator_controller_index = _init_dummy_controller(prosumer, [], ['ctrl_out', 'ctrl_out2'])
        responder_controller_index = _init_dummy_controller(prosumer, ['ctrl_in'], [])

        initiator_controller = prosumer.controller.loc[initiator_controller_index, 'object']
        responder_controller = prosumer.controller.loc[responder_controller_index, 'object']

        first_mapping = FluidMixMapping(container=prosumer,
                                        initiator_id=initiator_controller_index,
                                        responder_id=responder_controller_index,
                                        order=1)

        second_mapping = FluidMixMapping(container=prosumer,
                                         initiator_id=initiator_controller_index,
                                         responder_id=responder_controller_index,
                                         order=0)

        assert initiator_controller._get_mappings(prosumer)[1].object == first_mapping
        assert initiator_controller._get_mappings(prosumer)[0].object == second_mapping

    def test_1to1_fluidmix(self):
        """
        Check that the output of a controller can be successfully mapped to the input of another controller
        """
        prosumer = create_empty_prosumer_container()
        period, data_source = define_and_get_period_and_data_source(prosumer)

        initiator_controller_index = _init_dummy_controller(prosumer, [], ['ctrl_out', 'ctrl_out2'])
        responder_controller_index = _init_dummy_controller(prosumer, ['ctrl_in'], [])

        initiator_controller = prosumer.controller.loc[initiator_controller_index, 'object']
        responder_controller = prosumer.controller.loc[responder_controller_index, 'object']

        FluidMixMapping(container=prosumer,
                        initiator_id=initiator_controller_index,
                        responder_id=responder_controller_index,
                        order=0)

        mapped_values = [10, 2]
        initiator_controller.result_mass_flow_with_temp = [{FluidMixMapping.MASS_FLOW_KEY: mapped_values[0],
                                                            FluidMixMapping.TEMPERATURE_KEY: mapped_values[1]}]

        self._map(prosumer, initiator_controller)

        assert responder_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] == mapped_values[0]
        assert responder_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] == mapped_values[1]

    def test_2to1_fluimix_add(self):
        """
        Default 'application_operation' of a Generic Mapping is 'add'
        Which means that mapping 2 outputs to the same input will result in summing the outputs
        """
        prosumer = create_empty_prosumer_container()
        period, data_source = define_and_get_period_and_data_source(prosumer)

        initiator_controller1_index = _init_dummy_controller(prosumer, [], ['ctrl_out', 'ctrl_out2'])
        initiator_controller2_index = _init_dummy_controller(prosumer, [], ['ctrl_out', 'ctrl_out2'])
        responder_controller_index = _init_dummy_controller(prosumer, ['ctrl_in'], [])

        initiator_controller1 = prosumer.controller.loc[initiator_controller1_index, 'object']
        initiator_controller2 = prosumer.controller.loc[initiator_controller2_index, 'object']
        responder_controller = prosumer.controller.loc[responder_controller_index, 'object']

        FluidMixMapping(container=prosumer,
                        initiator_id=initiator_controller1_index,
                        responder_id=responder_controller_index,
                        order=0)

        FluidMixMapping(container=prosumer,
                        initiator_id=initiator_controller2_index,
                        responder_id=responder_controller_index,
                        order=0)

        mapped_values1 = [10, 2]
        mapped_values2 = [5, 8]
        initiator_controller1.result_mass_flow_with_temp = [{FluidMixMapping.MASS_FLOW_KEY: mapped_values1[0],
                                                             FluidMixMapping.TEMPERATURE_KEY: mapped_values1[1]}]
        initiator_controller2.result_mass_flow_with_temp = [{FluidMixMapping.MASS_FLOW_KEY: mapped_values2[0],
                                                             FluidMixMapping.TEMPERATURE_KEY: mapped_values2[1]}]

        self._map(prosumer, initiator_controller1)
        assert responder_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] == mapped_values1[0]
        assert responder_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] == mapped_values1[1]

        self._map(prosumer, initiator_controller2)
        res_m = mapped_values1[0] + mapped_values2[0]
        res_t = (mapped_values1[0] * mapped_values1[1] + mapped_values2[0] * mapped_values2[1]) / res_m
        assert responder_controller.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] == res_m
        assert responder_controller.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] == res_t

    def test_1to2_fluidmix(self):
        """
        Check that the output of a controller can be successfully mapped to the input of 2 downstream controllers
        """
        prosumer = create_empty_prosumer_container()
        period, data_source = define_and_get_period_and_data_source(prosumer)

        initiator_controller_index = _init_dummy_controller(prosumer, [], ['ctrl_out', 'ctrl_out2'])
        responder_controller1_index = _init_dummy_controller(prosumer, ['ctrl_in'], [])
        responder_controller2_index = _init_dummy_controller(prosumer, ['ctrl_in'], [])

        initiator_controller = prosumer.controller.loc[initiator_controller_index, 'object']
        responder_controller1 = prosumer.controller.loc[responder_controller1_index, 'object']
        responder_controller2 = prosumer.controller.loc[responder_controller2_index, 'object']

        FluidMixMapping(container=prosumer,
                        initiator_id=initiator_controller_index,
                        responder_id=responder_controller1_index,
                        order=0)

        FluidMixMapping(container=prosumer,
                        initiator_id=initiator_controller_index,
                        responder_id=responder_controller2_index,
                        order=1)

        mapped_values1 = [10, 2]
        mapped_values2 = [5, 8]

        initiator_controller.result_mass_flow_with_temp = [{FluidMixMapping.MASS_FLOW_KEY: mapped_values1[0],
                                                            FluidMixMapping.TEMPERATURE_KEY: mapped_values1[1]},
                                                           {FluidMixMapping.MASS_FLOW_KEY: mapped_values2[0],
                                                            FluidMixMapping.TEMPERATURE_KEY: mapped_values2[1]}]

        self._map(prosumer, initiator_controller)

        assert responder_controller1.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] == mapped_values1[0]
        assert responder_controller1.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] == mapped_values1[1]
        assert responder_controller2.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] == mapped_values2[0]
        assert responder_controller2.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] == mapped_values2[1]

    def test_mapping_loop(self):
        """
        Create a failing case where a loop is created in the mapping
        FixMe: dummy_controller_mid received 3 kg/s of water at 120°C, but then deliver 0 to dummy_controller_dmd
            This extra energy delivered by dummy_controller_prod disappear from the system
            This could be okay if dummy_controller_mid is a non-full storage but not in the general case
            dummy_controller_mid should maybe ask to run dummy_controller_prod a 2nd time to ask for the updated value
            OR: dummy_controller_mid should not forward the demand from dummy_controller_dmd to dummy_controller_prod
            but require only its own heat demand if any
        """
        prosumer = create_empty_prosumer_container()
        period, data_source = define_and_get_period_and_data_source(prosumer)

        # Create some controllers and mapping
        dummy_controller_prod_index = _init_dummy_controller(prosumer, [], [])
        dummy_controller_mid_index = _init_dummy_controller(prosumer, [], [])
        dummy_controller_dmd_index = _init_dummy_controller(prosumer, [], [])

        dummy_controller_prod = prosumer.controller.loc[dummy_controller_prod_index, 'object']
        dummy_controller_mid = prosumer.controller.loc[dummy_controller_mid_index, 'object']
        dummy_controller_dmd = prosumer.controller.loc[dummy_controller_dmd_index, 'object']

        dummy_controller_dmd.t_m_to_deliver = lambda container: (120, 30, np.array([3]))

        FluidMixMapping(container=prosumer,
                        initiator_id=dummy_controller_prod_index,
                        responder_id=dummy_controller_dmd_index,
                        order=0)

        FluidMixMapping(container=prosumer,
                        initiator_id=dummy_controller_prod_index,
                        responder_id=dummy_controller_mid_index,
                        order=1)

        FluidMixMapping(container=prosumer,
                        initiator_id=dummy_controller_mid_index,
                        responder_id=dummy_controller_dmd_index,
                        order=0)

        # dummy_controller_dmd and dummy_controller_mid required 3kg/s each from dummy_controller_prod
        tfeed_c, tret_c, m_tab_kg_per_s = dummy_controller_prod.t_m_to_deliver(prosumer)
        assert tfeed_c == pytest.approx(120.)
        assert tret_c == pytest.approx(30)
        assert m_tab_kg_per_s == pytest.approx(np.array([3, 3]))
        mass_flow_with_temp = []
        for m in m_tab_kg_per_s:
            mass_flow_with_temp.append({FluidMixMapping.MASS_FLOW_KEY: m, FluidMixMapping.TEMPERATURE_KEY: tfeed_c})
        dummy_controller_prod.finalize(prosumer, np.array([[]]), mass_flow_with_temp)

        # dummy_controller_dmd receive 3 kg/s from dummy_controller_prod
        assert dummy_controller_dmd.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] == pytest.approx(3)
        assert dummy_controller_dmd.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] == pytest.approx(120)

        # dummy_controller_mid receive 3 kg/s from dummy_controller_prod
        assert dummy_controller_mid.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] == pytest.approx(3)
        assert dummy_controller_mid.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] == pytest.approx(120)

        # dummy_controller_dmd required now nothing from dummy_controller_prod
        tfeed_c, tret_c, mdot_tab_kg_per_s = dummy_controller_mid.t_m_to_deliver(prosumer)
        assert (tfeed_c, tret_c, mdot_tab_kg_per_s) == pytest.approx((120, 120, np.array([0.])))
        mass_flow_with_temp = [{FluidMixMapping.TEMPERATURE_KEY: tfeed_c,
                                FluidMixMapping.MASS_FLOW_KEY: sum(mdot_tab_kg_per_s)}]

        dummy_controller_mid.finalize(prosumer, np.array([[]]), mass_flow_with_temp)

        assert dummy_controller_dmd.input_mass_flow_with_temp[FluidMixMapping.MASS_FLOW_KEY] == pytest.approx(3)
        assert dummy_controller_dmd.input_mass_flow_with_temp[FluidMixMapping.TEMPERATURE_KEY] == pytest.approx(120)
