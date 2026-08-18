from pandaprosumer.energy_system import create_empty_energy_system, add_net_to_energy_system, \
    add_pandaprosumer_to_energy_system

from pandaprosumer.create_controlled import (create_period)

def _create_energy_system(nets, prosumers, name="test_energy_system"):
    energy_system = create_empty_energy_system(name=name)
    sample_prosumer_period = prosumers[0].period
    create_period(energy_system, sample_prosumer_period.iloc[0]["resolution_s"],
                  sample_prosumer_period.iloc[0]["start"],
                  sample_prosumer_period.iloc[0]["end"],
                  timezone=sample_prosumer_period.iloc[0]["timezone"],
                  name=sample_prosumer_period.iloc[0]["name"])
    for net in nets:
        add_net_to_energy_system(energy_system, net, net_name=net.name)
    for prosumer in prosumers:
        add_pandaprosumer_to_energy_system(energy_system, prosumer, pandaprosumer_name=prosumer.name)
    return energy_system