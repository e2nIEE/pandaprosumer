from pandaprosumer.create import create_empty_prosumer_container, create_period


class TestPeriod:

    """
    Tests the period functionality of a prosumer object
    """

    def test_define(self):
        prosumer = create_empty_prosumer_container()
        assert not hasattr(prosumer, "period")
        create_period(prosumer, 1)
        assert hasattr(prosumer, "period")
        assert len(prosumer.period) == 1

    def test_period_properties(self):
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1,
                      name="foo",
                      start="2020-01-01 00:00:00",
                      end="2020-01-01 11:59:59",
                      timezone="utc")
        assert prosumer.period.iloc[0]["name"] == "foo"
        assert prosumer.period.iloc[0]["start"] == "2020-01-01 00:00:00"
        assert prosumer.period.iloc[0]["end"] == "2020-01-01 11:59:59"
        assert prosumer.period.iloc[0]["timezone"] == "utc"
        assert prosumer.period.iloc[0]["resolution_s"] == 1
