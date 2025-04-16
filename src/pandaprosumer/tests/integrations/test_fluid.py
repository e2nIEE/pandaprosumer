import pytest
from tests.data_sources.define_period import define_and_get_period_and_data_source
from pandaprosumer import *



class TestFluid:
    """
    Test the fluid property of a prosumer
    """

    def test_fluid_property(self):
        """
        Test the default fluid properties of a prosumer
        """
        prosumer = create_empty_prosumer_container()
        period, data_source = define_and_get_period_and_data_source(prosumer)

        assert prosumer.fluid.name == 'water'  # Default fluid is water
        assert prosumer.fluid.get_heat_capacity(293) == pytest.approx(4184.4)
        assert prosumer.fluid.get_density(293) == pytest.approx(998.21)

        # Adding new physical property to the fluid
        # source: https://www.engineeringtoolbox.com/water-liquid-gas-thermal-conductivity-temperature-pressure-d_2012.html
        prosumer.fluid.add_property('thermal_conductivity_1_bar',
                                    pandapipes.FluidPropertyPolynominal([t+273.15 for t in range(10, 100, 10)],
                                                                        [.57875, .59803, .61450, .62856, .64060,
                                                                         .65091, .65969, .66702, .67288],
                                                                        2),
                                    overwrite=True,
                                    warn_on_duplicates=False)

        assert prosumer.fluid.get_property('thermal_conductivity_1_bar', 293) == pytest.approx(0.5973198916)

    def test_change_fluid(self):
        """
        Try to use another fluid than water
        Note that using gases/ compressible fluids will probably lead to errors
        """
        prosumer = create_empty_prosumer_container(fluid='air')
        period, data_source = define_and_get_period_and_data_source(prosumer)

        assert prosumer.fluid.name == 'air'
        assert prosumer.fluid.get_heat_capacity(293) == pytest.approx(1007)
        assert prosumer.fluid.get_density(293) == pytest.approx(1.188)
