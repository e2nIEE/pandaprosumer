from pandaprosumer import (create_controlled_heat_demand, create_controlled_heat_storage,
                           create_empty_prosumer_container, create_period)
from pandaprosumer.mapping import GenericEnergySystemMapping, GenericMapping


def _prosumer():
    prosumer = create_empty_prosumer_container()
    create_period(prosumer, 3600, start="2020-01-01 00:00:00", end="2020-01-01 03:59:59", timezone="utc")
    return prosumer


def test_generic_responders_skip_mappings_into_another_container():
    """
    A generic output mapped into another container (e.g. a CHP's electrical output coupled
    to a grid) must not be looked up among this prosumer's controllers: the responder index
    belongs to the other container (KeyError, or worse, a wrong controller).
    """
    prosumer = _prosumer()
    storage = create_controlled_heat_storage(prosumer, q_capacity_kwh=100, order=0)
    demand = create_controlled_heat_demand(prosumer, t_feed_demand_c=70, t_return_demand_c=40, order=1)
    other = _prosumer()
    for _ in range(5):
        create_controlled_heat_demand(other, t_feed_demand_c=70, t_return_demand_c=40)

    GenericMapping(prosumer, initiator_id=storage, initiator_column="q_delivered_kw",
                   responder_id=demand, responder_column="q_received_kw")
    GenericEnergySystemMapping(prosumer, initiator_id=storage, initiator_column="q_delivered_kw",
                               responder_net=other, responder_id=4, responder_column="q_received_kw")

    controller = prosumer.controller.loc[storage, "object"]
    assert controller._get_generic_mapped_responders(prosumer) == [prosumer.controller.loc[demand, "object"]]
