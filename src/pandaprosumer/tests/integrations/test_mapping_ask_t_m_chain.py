import numpy as np
import pytest

from pandaprosumer.mapping import GenericMapping
from pandaprosumer.tests.integrations.base_controller import BaseControllerData

from ..create_elements_controllers import *


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


class TestMappingAskTMChain:
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

    def test_1to1_fluidmix(self):
        """
        Check that t_m_to_deliver can access the info of the required t_m_to_receive by a downstream controller
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

        responder_controller.t_m_to_receive = lambda container: (100, 30.5, 3.5)

        assert initiator_controller.t_m_to_deliver(prosumer) == pytest.approx((100, 30.5, [3.5]))

    def test_2to1_fluimix_add(self):
        """
        Check that each controller can access the info of the required t_m_to_receive by a downstream controller
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

        responder_controller.t_m_to_receive = lambda container: (100, 30.5, 3.5)

        assert initiator_controller1.t_m_to_deliver(prosumer) == pytest.approx((100, 30.5, [3.5]))
        assert initiator_controller2.t_m_to_deliver(prosumer) == pytest.approx((100, 30.5, [3.5]))

    def test_1to2_fluidmix(self):
        """
        Check that t_m_to_deliver can access the info of the required t_m_to_receive by 2 downstream controllers,
        and calculate which temperature and mass flow it should supply such as each one get what the correct amount
        of energy
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

        tf1 = 140
        tr1 = 30
        m1 = 1.5
        tf2 = 120
        tr2 = 35
        m2 = 2

        responder_controller1.t_m_to_receive = lambda container: (tf1, tr1, m1)
        responder_controller2.t_m_to_receive = lambda container: (tf2, tr2, m2)

        tfm, trm, mm = initiator_controller.t_m_to_deliver(prosumer)
        assert tfm == pytest.approx(max(tf1, tf2))
        assert len(mm) == 2
        assert trm == pytest.approx((tr1 * mm[0] + tr2 * mm[1]) / (mm[0] + mm[1]))
        assert (tfm - tr1) * mm[0] == pytest.approx((tf1 - tr1) * m1)
        assert (tfm - tr2) * mm[1] == pytest.approx((tf2 - tr2) * m2)
        assert mm == pytest.approx([m1, m2 * (tf2 - tr2) / (tfm - tr2)])
