# Copyright (c) 2023 TECNALIA Research and Innovation
"""Module with the class PvProduction. It calculates the PV production, given a certain location.
It uses the library pvlib (https://github.com/pvlib/pvlib-python)
to interface with PVGIS (https://re.jrc.ec.europa.eu/pvg_tools/en/).

For the use in SENERGY NETS the following inputs must be defined by the user:

    - latitude (of the site)
    - longitude (of the site)
    - raddatabase (database for radiation)
    - surface_tilt
    - surface_azimuth
    - peakpower
    - loss

Raises
------
ValueError
    If any of the expected keys is missing, a Value Error will be raised
"""

from pvlib.iotools import get_pvgis_hourly

def rename_df_units(dataframe):
    """Changes the keys including the units in the dataframe output of pvlib / PVGIS

    Parameters
    ----------
    dataframe : Pandas dataframe
        the pandas dataframe output of pvlib / PVGIS
    """

    mapping_df = {"P":"p_w",
                  "poa_global":"poa_global_w_m2",
                  "poa_direct":"poa_direct_w_m2",
                  "poa_sky_diffuse" : "poa_sky_diffuse_w_m2",
                  "poa_ground_diffuse" : "poa_ground_diffuse_w_m2",
                  "solar_elevation" : "solar_elevation_deg",
                  "temp_air" : "temp_air_degC",
                  "wind_speed" : "wind_speed_m_s",
                  "Int" : "solar_rad_reconstr_bool"}
    dataframe.rename(
    columns=mapping_df,
    inplace=True,
    )



class PvProduction:
    """
    Calculation estimate of hourly PV production.
    It uses PVGIS. A Graphical User Interface on PVGIS can be seen here:
        https://re.jrc.ec.europa.eu/pvg_tools/en/

    It uses as a submodule the library pvlib-python available here:
        https://github.com/pvlib/pvlib-python

    Documentation of pvlib-python can be found here:
        https://pvlib-python.readthedocs.io/en/stable/

    In SENERGY-NETS we are forcing only the input:
        - PV calculation: enabled (not default)

    A set of inputs must be provided by the user:

        - latitude - In decimal degrees, between -90 and 90, north is positive (ISO 19115)
        - longitude - In decimal degrees, between -180 and 180, east is positive (ISO 19115)
        - raddatabase - Name of radiation database.
        - surface_tilt - Tilt angle from horizontal plane. Ignored for two-axis tracking.
        - surface_azimuth - Orientation (azimuth angle) of the (fixed) plane. Counter-clockwise from north (north=0, south=180). This is offset 180 degrees from the convention used by PVGIS. Ignored for tracking systems
        - peakpower - Nominal power of PV system in kW.
        - loss - Sum of PV system losses in percent.

    All the other inptus are optional, i.e. if the user does not provide them, then the default values are used.

        - start/end of the time series: First/last year of the radiation time series.
        - components: True if output all the components of solar radiation (beam, diffuse, and reflected)
        - horizon: Consider horizon effects computed by PVGIS
        - PV technology: Default technology is crystSi
        - Mounting Place: Default is set to free
        - Tracking type: Default is set to fixed
        - Optimal surface tilt / angle: Defauls is set to not calculated
        - URL:  https://re.jrc.ec.europa.eu/api/

    """

    def __init__(self, inputs):
        """Initialisation of the class"""
        self.inputs = inputs

        self.output = {}

    def pv_inputs_validation(self):
        """Method for the validation of the inputs. It checks for the inputs by the user and all
        the mandatory expected keys have been input.

        Raises
        ------
        ValueError
            If any of the expected keys is missing, a Value Error will be raised.
        """
        expected_keys = [
            "latitude",
            "longitude",
            "raddatabase",
            "surface_tilt",
            "surface_azimuth",
            "peakpower",
            "loss",
        ]

        actual_keys = self.inputs.keys()

        missing_elements = []

        for element in expected_keys:
            if element not in actual_keys:
                missing_elements.append(element)

        if not missing_elements:
            # self.inputs["start"] = None
            # self.inputs["end"] = None
            # self.inputs["components"] = True
            # self.inputs["usehorizon"] = True
            # self.inputs["userhorizon"] = None
            self.inputs["pvcalculation"] = True
            # self.inputs["pvtechchoice"] = "crystSi"
            # self.inputs["mountingplace"] = "free"
            # self.inputs["trackingtype"] = 0
            # self.inputs["optimal_surface_tilt"] = False
            # self.inputs["optimalangles"] = False
            # self.inputs["outputformat"] = "json"
            # self.inputs["url"] = "https://re.jrc.ec.europa.eu/api/v5_2/seriescalc?"
            # self.inputs["map_variables"] = True
            # self.inputs["timeout"] = 30

        else:
            raise ValueError("keys are missing", missing_elements)

    def calculate_pv(self):
        """Validate inputs and then calculate PV production
        In the dataframe, the following quantities are calculated:
            p_w                        float   PV system power (W)
            poa_global_w_m2            float   Global irradiance on inclined plane (W/m^2)
            poa_direct_w_m2            float   Beam (direct) irradiance on inclined plane (W/m^2)
            poa_sky_diffuse_w_m2       float   Diffuse irradiance on inclined plane (W/m^2)
            poa_ground_diffuse_w_m2    float   Reflected irradiance on inclined plane (W/m^2)
            solar_elevation_deg        float   Sun height/elevation (degrees)
            temp_air_degC              float   Air temperature at 2 m (degrees Celsius)
            wind_speed_m_s             float   Wind speed at 10 m (m/s)
            solar_rad_reconstr_bool    int     Solar radiation reconstructed (1/0)
        """
        try:
            self.pv_inputs_validation()
            self.output = get_pvgis_hourly(**self.inputs)
            rename_df_units(self.output[0])
        except Exception as err:
            print(f"Unexpected {err=}, {type(err)=}")
            raise