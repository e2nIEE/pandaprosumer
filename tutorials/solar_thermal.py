
import pandas as pd

from pandapower.timeseries.data_sources.frame_data import DFData
from pandaprosumer.create import create_empty_prosumer_container, create_period
from pandaprosumer.create_controlled import (create_controlled_const_profile, create_controlled_solar_thermal)
from pandaprosumer.mapping import GenericMapping
from pandaprosumer.run_time_series import run_timeseries


st_params = {}


start = '2005-01-01 00:30:00'
end = '2005-01-05 00:29:59'
time_resolution_s = 3600        # 15 min
frequency = '60min'

data = pd.read_excel('data/senergy_nets_example_solar_thermal.xlsx')

data = data.iloc[3000:3096].copy()
data["time"] = pd.to_datetime(data["time"], format="%Y%m%d:%H%M")

# Optional: als Index setzen
data.set_index("time", inplace=True)

# Ergebnis prüfen
print(list(data.columns))
print(data)


dur = pd.date_range(start=start, end=end, freq=frequency, tz='utc')
data.index = dur
data_input = DFData(data)

input_params = ['Beam Solar Radiation [W/m2]',
                 'Diffuse Solar Radiation [W/m2]',
                 'Ground Solar Radiation [W/m2]',
                 'Radiation incidence angle [deg]',
                 'Ambient temperature [C]',
                 'Inlet temperature [C]',
                 'Inlet mass flow rate [kg/h]']
result_params = [
                    "beam_solar_radiation_cp",
                    "diffuse_solar_radiation_cp",
                    "ground_solar_radiation_cp",
                    "radiation_incidence_angle_cp",
                    "ambient_temperature_cp",
                    "inlet_temperature_cp",
                    "inlet_mass_flow_rate_cp"
                ]




prosumer = create_empty_prosumer_container()

period = create_period(prosumer, time_resolution_s, start, end, 'utc', 'default')

cp_index = create_controlled_const_profile(
    prosumer, input_params, result_params, data_input, period)

st_index = create_controlled_solar_thermal(prosumer, name="solar_thermal_plant", level=1, order=0, **st_params)

GenericMapping(
    prosumer,
    initiator_id=cp_index,
    initiator_column=["beam_solar_radiation_cp",
                    "diffuse_solar_radiation_cp",
                    "ground_solar_radiation_cp",
                    "radiation_incidence_angle_cp",
                    "ambient_temperature_cp",
                    "inlet_temperature_cp",
                    "inlet_mass_flow_rate_cp"],
    responder_id=st_index,
    responder_column=['beam_solar_radiation_w_m2',
                      'diffuse_solar_radiation_w_m2',
                      'ground_solar_radiation_w_m2',
                      'radiation_incidence_angle_deg',
                      'ambient_temperature_C',
                      'inlet_temperature_C',
                      'inlet_mass_flow_rate_kg_h',
                      ]
)

run_timeseries(prosumer)

