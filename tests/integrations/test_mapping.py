import pytest
import re
from pandaprosumer.mapping import GenericMapping
from tests.integrations.base_controller import BaseControllerData
from pandaprosumer import *
from tests.data_sources.define_period import define_and_get_period_and_data_source


def _init_dummy_controller(prosumer, input_columns, result_columns, level=0, order=0, name = "", **kwargs):
    dummy_controller_data = BaseControllerData(
        input_columns=input_columns,
        result_columns=result_columns
    )
    BasicProsumerController(prosumer,
                            dummy_controller_data,
                            order=order,
                            level=level,
                            name = name)
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

    def test_create_generic_mapping(self):
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

        GenericMapping(container=prosumer,
                       initiator_id=dummy_controller_index,
                       initiator_column="ctrl_out",
                       responder_id=dummy_controller_index2,
                       responder_column="ctrl_in",
                       order=0)

        assert len(dummy_controller._get_mappings(prosumer)) == 1
        assert len(dummy_controller2._get_mappings(prosumer)) == 0

    def test_generic_order(self):
        """
        Check that controller._get_mappings(prosumer) return the mapping in the good order
        """
        prosumer = create_empty_prosumer_container()
        period, data_source = define_and_get_period_and_data_source(prosumer)

        initiator_controller_index = _init_dummy_controller(prosumer, [], ['ctrl_out', 'ctrl_out2'])
        responder_controller_index = _init_dummy_controller(prosumer, ['ctrl_in'], [])

        initiator_controller = prosumer.controller.loc[initiator_controller_index, 'object']
        responder_controller = prosumer.controller.loc[responder_controller_index, 'object']

        first_mapping = GenericMapping(container=prosumer,
                                       initiator_id=initiator_controller_index,
                                       initiator_column="ctrl_out",
                                       responder_id=responder_controller_index,
                                       responder_column="ctrl_in",
                                       order=0)

        second_mapping = GenericMapping(container=prosumer,
                                        initiator_id=initiator_controller_index,
                                        initiator_column="ctrl_out2",
                                        responder_id=responder_controller_index,
                                        responder_column="ctrl_in",
                                        order=1)

        assert initiator_controller._get_mappings(prosumer)[0].object == first_mapping
        assert initiator_controller._get_mappings(prosumer)[1].object == second_mapping

    def test_generic_order_reverse(self):
        """
        Check that controller._get_mappings(prosumer) return the mapping in the good order
        """
        prosumer = create_empty_prosumer_container()
        period, data_source = define_and_get_period_and_data_source(prosumer)

        initiator_controller_index = _init_dummy_controller(prosumer, [], ['ctrl_out', 'ctrl_out2'])
        responder_controller_index = _init_dummy_controller(prosumer, ['ctrl_in'], [])

        initiator_controller = prosumer.controller.loc[initiator_controller_index, 'object']
        responder_controller = prosumer.controller.loc[responder_controller_index, 'object']

        first_mapping = GenericMapping(container=prosumer,
                                       initiator_id=initiator_controller_index,
                                       initiator_column="ctrl_out",
                                       responder_id=responder_controller_index,
                                       responder_column="ctrl_in",
                                       order=1)

        second_mapping = GenericMapping(container=prosumer,
                                        initiator_id=initiator_controller_index,
                                        initiator_column="ctrl_out2",
                                        responder_id=responder_controller_index,
                                        responder_column="ctrl_in",
                                        order=0)

        assert initiator_controller._get_mappings(prosumer)[1].object == first_mapping
        assert initiator_controller._get_mappings(prosumer)[0].object == second_mapping

    def test_1to1_generic(self):
        """
        Check that the output of a controller can be successfully mapped to the input of another controller
        """
        prosumer = create_empty_prosumer_container(check_order=False)
        period, data_source = define_and_get_period_and_data_source(prosumer)

        initiator_controller_index = _init_dummy_controller(prosumer, [], ['ctrl_out', 'ctrl_out2'])
        responder_controller_index = _init_dummy_controller(prosumer, ['ctrl_in'], [])

        initiator_controller = prosumer.controller.loc[initiator_controller_index, 'object']
        responder_controller = prosumer.controller.loc[responder_controller_index, 'object']

        GenericMapping(container=prosumer,
                       initiator_id=initiator_controller_index,
                       initiator_column="ctrl_out",
                       responder_id=responder_controller_index,
                       responder_column="ctrl_in",
                       order=0)

        mapped_values = [10, 2]
        initiator_controller.step_results = np.array([mapped_values])

        self._map(prosumer, initiator_controller)

        assert responder_controller.inputs[0][0] == mapped_values[0]

    def test_2to1_generic_add(self):
        """
        Default 'application_operation' of a Generic Mapping is 'add'
        Which means that mapping 2 outputs to the same input will result in summing the outputs
        """
        prosumer = create_empty_prosumer_container(check_order = False)
        period, data_source = define_and_get_period_and_data_source(prosumer)

        initiator_controller1_index = _init_dummy_controller(prosumer, [], ['ctrl_out', 'ctrl_out2'])
        initiator_controller2_index = _init_dummy_controller(prosumer, [], ['ctrl_out', 'ctrl_out2'])
        responder_controller_index = _init_dummy_controller(prosumer, ['ctrl_in'], [])

        initiator_controller1 = prosumer.controller.loc[initiator_controller1_index, 'object']
        initiator_controller2 = prosumer.controller.loc[initiator_controller2_index, 'object']
        responder_controller = prosumer.controller.loc[responder_controller_index, 'object']

        GenericMapping(container=prosumer,
                       initiator_id=initiator_controller1_index,
                       initiator_column="ctrl_out",
                       responder_id=responder_controller_index,
                       responder_column="ctrl_in",
                       order=0)

        GenericMapping(container=prosumer,
                       initiator_id=initiator_controller2_index,
                       initiator_column="ctrl_out2",
                       responder_id=responder_controller_index,
                       responder_column="ctrl_in",
                       order=1)

        mapped_values1 = [10, 2]
        initiator_controller1.step_results = np.array([mapped_values1])
        mapped_values2 = [5, 8]
        initiator_controller2.step_results = np.array([mapped_values2])

        self._map(prosumer, initiator_controller1)
        assert responder_controller.inputs[0][0] == mapped_values1[0]

        self._map(prosumer, initiator_controller2)
        assert responder_controller.inputs[0][0] == mapped_values1[0] + mapped_values2[1]

    def test_1to2_generic(self):
        """
        Check that the output of a controller can be successfully mapped to the input of 2 downstream controllers
        """
        prosumer = create_empty_prosumer_container(check_order=False)
        period, data_source = define_and_get_period_and_data_source(prosumer)

        initiator_controller_index = _init_dummy_controller(prosumer, [], ['ctrl_out', 'ctrl_out2'])
        responder_controller1_index = _init_dummy_controller(prosumer, ['ctrl_in'], [])
        responder_controller2_index = _init_dummy_controller(prosumer, ['ctrl_in'], [])

        initiator_controller = prosumer.controller.loc[initiator_controller_index, 'object']
        responder_controller1 = prosumer.controller.loc[responder_controller1_index, 'object']
        responder_controller2 = prosumer.controller.loc[responder_controller2_index, 'object']

        GenericMapping(container=prosumer,
                       initiator_id=initiator_controller_index,
                       initiator_column="ctrl_out",
                       responder_id=responder_controller1_index,
                       responder_column="ctrl_in",
                       order=0)

        GenericMapping(container=prosumer,
                       initiator_id=initiator_controller_index,
                       initiator_column="ctrl_out",
                       responder_id=responder_controller2_index,
                       responder_column="ctrl_in",
                       order=1)

        mapped_values = [10, 2]
        initiator_controller.step_results = np.array([mapped_values])

        self._map(prosumer, initiator_controller)

        assert responder_controller1.inputs[0][0] == mapped_values[0]
        assert responder_controller2.inputs[0][0] == mapped_values[0]

    def test_generic_list(self):
        """
        Check that generic mapping with multiple columns works
        """
        prosumer = create_empty_prosumer_container()
        period, data_source = define_and_get_period_and_data_source(prosumer)

        initiator_controller_index = _init_dummy_controller(prosumer, [], ['ctrl_out', 'ctrl_out2'])
        responder_controller_index = _init_dummy_controller(prosumer, ['ctrl_in', 'ctrl_in2'], [])

        initiator_controller = prosumer.controller.loc[initiator_controller_index, 'object']
        responder_controller = prosumer.controller.loc[responder_controller_index, 'object']

        mapping = GenericMapping(container=prosumer,
                                 initiator_id=initiator_controller_index,
                                 initiator_column=["ctrl_out", "ctrl_out2"],
                                 responder_id=responder_controller_index,
                                 responder_column=["ctrl_in", "ctrl_in2"],
                                 order=0)

        assert initiator_controller._get_mappings(prosumer)[0].object == mapping

    def test_check_controllers_orders(self):
        prosumer = create_empty_prosumer_container()
        period, data_source = define_and_get_period_and_data_source(prosumer)

        initiator_controller_index = _init_dummy_controller(prosumer, [], ['ctrl_out', 'ctrl_out2'],level=0,order=0)
        responder_controller_index = _init_dummy_controller(prosumer, ['ctrl_in'], [],level=0,order=0)

        initiator_controller = prosumer.controller.loc[initiator_controller_index, 'object']
        responder_controller = prosumer.controller.loc[responder_controller_index, 'object']

        first_mapping = GenericMapping(container=prosumer,
                                       initiator_id=initiator_controller_index,
                                       initiator_column="ctrl_out",
                                       responder_id=responder_controller_index,
                                       responder_column="ctrl_in",
                                       order=0)

        second_mapping = GenericMapping(container=prosumer,
                                        initiator_id=initiator_controller_index,
                                        initiator_column="ctrl_out2",
                                        responder_id=responder_controller_index,
                                        responder_column="ctrl_in",
                                        order=1)

        with pytest.raises(ValueError, match=re.escape("Controller order error: Initiator '' (order: 0) must be executed before responder '' (order: 0).")):
            self._map(prosumer, initiator_controller)

    def test_check_levels(self):
        prosumer = create_empty_prosumer_container()
        period, data_source = define_and_get_period_and_data_source(prosumer)

        initiator_controller_index = _init_dummy_controller(prosumer, [], ['ctrl_out', 'ctrl_out2'], level=0, order=0,name = 'heat_pump_controller')
        responder_controller_index = _init_dummy_controller(prosumer, ['ctrl_in'], [], level=1, order=0,name = 'heat_pump_controller')

        initiator_controller = prosumer.controller.loc[initiator_controller_index, 'object']
        responder_controller = prosumer.controller.loc[responder_controller_index, 'object']

        first_mapping = GenericMapping(container=prosumer,
                                       initiator_id=initiator_controller_index,
                                       initiator_column="ctrl_out",
                                       responder_id=responder_controller_index,
                                       responder_column="ctrl_in",
                                       order=0)

        second_mapping = GenericMapping(container=prosumer,
                                        initiator_id=initiator_controller_index,
                                        initiator_column="ctrl_out2",
                                        responder_id=responder_controller_index,
                                        responder_column="ctrl_in",
                                        order=1)

        with pytest.raises(ValueError, match=re.escape(
                "Level error: Not all controllers have the same level (excluding ConstProfile). Found levels: {0, 1}.")):
            initiator_controller.initialize_control(prosumer)

# ToDO: Test merit order (both ways)