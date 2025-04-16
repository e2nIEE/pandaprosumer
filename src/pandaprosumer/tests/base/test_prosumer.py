from pandaprosumer.create import create_empty_prosumer_container


class TestProsumer:

    """
    Tests that the prosumer is initialized with the expected properties and columns of child DataFrames
    """

    def test_create(self):
        prosumer = create_empty_prosumer_container()
        assert hasattr(prosumer, "controller")
        assert hasattr(prosumer, "mapping")
        assert hasattr(prosumer, "time_series")
        assert hasattr(prosumer, "name")
        assert hasattr(prosumer, "version")

    def test_create_with_custom_name(self):
        prosumer = create_empty_prosumer_container(name="foo")
        assert prosumer.name == "foo"

    def test_controller_columns(self):
        prosumer = create_empty_prosumer_container()
        expected = sorted(['in_service', 'level', 'object', 'order'])
        assert sorted(prosumer.controller.columns.to_list()) == expected

    def test_mapping_columns(self):
        prosumer = create_empty_prosumer_container()
        expected = sorted(['initiator', 'object', 'order', 'responder'])
        assert sorted(prosumer.mapping.columns.to_list()) == expected

    def test_time_series_columns(self):
        prosumer = create_empty_prosumer_container()
        expected = sorted(['name', 'element', 'element_index', 'period_index', 'data_source'])
        assert sorted(prosumer.time_series.columns.to_list()) == expected
