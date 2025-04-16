"""
Module containing the ConstProfileController class.
"""

from pandapower.timeseries.data_sources.frame_data import DFData
from .mapped import MappedController
from pandaprosumer.mapping import FluidMixMapping

try:
    import pandaplan.core.pplog as logging
except ImportError:
    import logging

logger = logging.getLogger(__name__)



class ConstProfileController(MappedController):
    """
    Controller for constant profiles.
    Map the values from a DataFrame f_data to its output for mapping to other controllers.
    Should be executed first (lowest level/order)
    Inherit from MappedController but not from BasicProsumerController as can be mapped to the input of other
    controllers but without asking for the required mass flow and temperatures.

    :param prosumer: The prosumer object
    :param const_object: The constant object
    :param df_data: The data frame data
    :param order: The order of the controller
    :param level: The level of the controller
    :param in_service: The in-service status of the controller
    :param drop_same_existing_ctrl: Whether to drop existing controllers of the same type
    :param overwrite: Whether to overwrite existing controllers
    :param kwargs: Additional keyword arguments
    """

    @classmethod
    def name(cls):
        return "const_profile_control"

    def __init__(self, prosumer, const_object, df_data: DFData, order=-1, level=-1, in_service=True, index=None,
                 drop_same_existing_ctrl=False, overwrite=False, name=None, matching_params=None, temp_fluid_map_idx = None, mdot_fluid_map_idx= None, **kwargs):
        """
        Initializes the ConstProfileController.
        """
        super().__init__(prosumer, const_object, order, level, in_service, index,
                         drop_same_existing_ctrl, overwrite, name, matching_params, **kwargs)

        self.has_elements = False
        self.df_data = df_data

        self.temp_fluid_map_idx = temp_fluid_map_idx
        self.mdot_fluid_map_idx = mdot_fluid_map_idx

    def control_step(self, prosumer):
        """
        Executes the control step for the controller.

        :param prosumer: The prosumer object
        """
        super().control_step(prosumer)
        # ToDo: error message if column not found in data_source
        print(self.time)
        results = self.df_data.get_time_step_value(time_step=self.time, profile_name=self.input_columns).reshape(1, -1)
        results = results.astype('float64')

        if self.temp_fluid_map_idx is not None and self.mdot_fluid_map_idx is not None:
            result_fluid_mix = [{FluidMixMapping.TEMPERATURE_KEY: results[0][self.temp_fluid_map_idx],
                             FluidMixMapping.MASS_FLOW_KEY: results[0][self.mdot_fluid_map_idx]}]
            self.finalize(prosumer, results,result_fluid_mix)
        else:
            self.finalize(prosumer, results)

        self.applied = True
        self.applied = True
