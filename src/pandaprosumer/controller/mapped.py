"""
Module containing the MappedController class.
"""

import numpy as np
import pandas as pd
import logging as pplog

from pandapower.control.basic_controller import Controller
from pandaprosumer.mapping.fluid_mix import FluidMixMapping

logger = pplog.getLogger(__name__)


class MappedController(Controller):
    """
    Base class for all prosumer controllers that are associated to an element and can be mapped.

    :param container: The prosumer/net/energy_system object
    :param basic_prosumer_object: The basic prosumer object
    :param order: The order of the controller
    :param level: The level of the controller
    :param in_service: The in-service status of the controller
    :param index: The index of the controller
    :param drop_same_existing_ctrl: Whether to drop existing controllers of the same type
    :param overwrite: Whether to overwrite existing controllers
    :param name: The name of the controller
    :param matching_params: Matching parameters for the controller
    :param kwargs: Additional keyword arguments
    """

    @classmethod
    def name(cls):
        return "mapped_controller"

    def __init__(self, container, basic_prosumer_object, order=0, level=0, in_service=True, index=None,
                 drop_same_existing_ctrl=False, overwrite=False, name=None, matching_params=None, **kwargs):
        """
        Initializes the BasicProsumerController.
        """
        super().__init__(container, in_service, order, level, index, False,
                         drop_same_existing_ctrl, True, overwrite,
                         matching_params, **kwargs)

        if getattr(container, "check_order", False):
            if isinstance(order, list):
                if len(order) == 1:
                    order = order[0]
                else:
                    raise ValueError("order must be an integer, or the check should be set to False.")
            self.order = int(order)

            if isinstance(level, list):
                if len(level) == 1:
                    level = level[0]
                else:
                    raise ValueError("order must be an integer, or the check should be set to False.")
            self.level = int(level)

        self.matching_params = dict() if matching_params is None else matching_params
        self.obj = basic_prosumer_object
        self.has_elements = hasattr(self.obj, "element_index") or np.iterable(self.obj) and hasattr(self.obj[0], "element_index")
        self._nb_elements = len(self.obj) if self.has_elements and np.iterable(self.obj) else 1
        self.has_period = False

        if np.iterable(self.obj):
            self.input_columns = [name for obj in self.obj for name in obj.input_columns]  # [obj.input_columns for obj in self.obj]
            self.result_columns = [name for obj in self.obj for name in obj.result_columns]  # [obj.result_columns for obj in self.obj]
            self.inputs = np.full([self._nb_elements, len(self.input_columns)], np.nan)  # np.full([self._nb_elements, np.shape(self.input_columns)[1]], np.nan)
            self.step_results = np.full([self._nb_elements, len(self.result_columns)], np.nan)  # np.full([self._nb_elements, np.shape(self.result_columns)[1]], np.nan)
            if hasattr(self.obj[0], "period_index"):
                self.has_period = True
                self.period_index = self.obj[0].period_index
                self.start = container.period.at[self.obj[0].period_index, 'start']
                self.end = container.period.at[self.obj[0].period_index, 'end']
                self.tz = container.period.at[self.obj[0].period_index, 'timezone']
                self.resol = int(container.period.at[self.obj[0].period_index, 'resolution_s'])
                self.time_index = pd.date_range(self.start, self.end, freq='%ss' % self.resol, tz=self.tz)
                self.res = np.zeros([self._nb_elements, len(self.time_index), len(self.result_columns)])
            if self.has_elements:
                self.element_name = [obj.element_name for obj in self.obj]
                self.element_index = [obj.element_index for obj in self.obj]
                self.element_instance = [container[name].loc[index, :] for name, index in zip(self.element_name, self.element_index)]
        else:
            self.input_columns = self.obj.input_columns
            self.result_columns = self.obj.result_columns
            self.inputs = np.full([self._nb_elements, len(self.input_columns)], np.nan)
            self.step_results = np.full([self._nb_elements, len(self.result_columns)], np.nan)
            if hasattr(self.obj, "period_index") and self.obj.period_index is not None:
                self.has_period = True
                self.period_index = self.obj.period_index
                self.start = container.period.at[self.obj.period_index, 'start']
                self.end = container.period.at[self.obj.period_index, 'end']
                self.tz = container.period.at[self.obj.period_index, 'timezone']
                self.resol = int(container.period.at[self.obj.period_index, 'resolution_s'])
                self.time_index = pd.date_range(self.start, self.end, freq='%ss' % self.resol, tz=self.tz)
                self.res = np.zeros([self._nb_elements, len(self.time_index), len(self.result_columns)])

            if self.has_elements:
                self.element_name = self.obj.element_name
                self.element_index = self.obj.element_index
                self.element_instance = container[self.element_name].loc[self.element_index, :]

        # ToDo: create the input_mass_flow_with_temp and result_mass_flow_with_temp attribute only when necessary
        #    using inheritance for models who can only have input or output fluid
        self.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: np.nan,
                                          FluidMixMapping.MASS_FLOW_KEY: np.nan}
        self.result_mass_flow_with_temp = []
        self.time = None
        self.name = name
        self.applied = None
        # Keep the return temperature for the next time step (used only for models with fluid input)
        self.t_keep_return_c = np.nan

    def is_converged(self, container):
        """
            Check if controller already was applied
        """
        return self.applied
    
    def level_reset(self, container):
        """
        Resets the level for the controller.

        :param container: The container object
        """
        self.applied = False

    def _get_input(self, input_name, container=None):
        """
        Get the value of an input for the controller.

        If the input is not found in the input_columns, raise a KeyError.
        If the input value is nan (nothing is mapped to it), and if 'container' is provided,
        try to get the value from the element associated with the controller.

        :param input_name: The input name
        :param container: The container object
        :return: The value of the input for the controller
        """
        if input_name not in self.input_columns:
            raise KeyError(f"Input '{input_name}' not found in the input columns of the controller")

        index = self.input_columns.index(input_name)
        input_value = self.inputs[0, index]

        if np.isnan(input_value) and container:
            element_value = self._get_element_param(container, input_name)
            return element_value if element_value is not None else np.nan

        return input_value

    def _get_element_param(self, container, attr_name):
        """
        Get a value in the element associate with this controller
        Assume that len(self.element_index) == 1 (only one element associated with the controller)

        NB: Need the container reference, can't use self.element_instance as it is not a reference
        to the instance and will not be up-to-date if a value changed after the controller creation

        :param container: The container (prosumer) object
        :param attr_name: The attribute name
        :return: The value of the attribute for the element associated to the controller
        (default to None if the attribute does not exist)
        """
        if hasattr(container[self.element_name], attr_name):
            return container[self.element_name].loc[self.element_index[0], attr_name]
        else:
            return None

    def _get_mappings(self, container):
        """
        Returns a list of mappings for which this controller is the initiator.

        :param container: The container object
        :return: List of mappings
        """
        if hasattr(container, "mapping"):
            return [item for item in container.mapping[container.mapping["initiator"] == self.index]
            .sort_values("order")[["object", "responder"]].itertuples()]
        else:
            return []
        # return [item for item in container.mapping[container.mapping["initiator"] == self.index]
        # .sort_values("order")[["mapping", "responder"]].itertuples()]

    def _get_mapped_responders(self, container, remove_duplicate=True):
        """
        Returns a list of all the controllers for which this controller is the initiator.

        :param container: The container object
        :return: List of mapped responders
        """
        list_responders = [item.object.responder_net.controller.loc[item.responder]["object"] for item in
                           container.mapping[(container.mapping["initiator"] == self.index) &
                                             [r.no_chain == False for r in container.mapping.object]].sort_values("order")
                           [["object", "responder"]].itertuples()]
        
        if remove_duplicate:
            return list(dict.fromkeys(list_responders))
        else:
            return list_responders

    def _get_generic_mapped_responders(self, prosumer):
        """
        Returns a list of all the controllers for which this controller is the responder.

        :param prosumer: The prosumer object
        :return: List of mapped responders
        """
        return [prosumer.controller.loc[item.responder]["object"] for item in
                prosumer.mapping[prosumer.mapping["initiator"] == self.index].sort_values("order")
                [["object", "responder"]].itertuples()]

    def _get_mapped_initiators(self, container, remove_duplicate=True):
        """
        Returns a list of all the controllers for which this controller is the responder.

        :param container: The container object
        :return: List of mapped initiators
        """
        list_initiators = [item.object.responder_net.controller.loc[item.initiator]["object"] for item in
                           container.mapping[(container.mapping["responder"] == self.index) &
                                             [r.no_chain == False for r in container.mapping.object]].sort_values("order")
                           [["object", "initiator"]].itertuples()]

        if remove_duplicate:
            return list(dict.fromkeys(list_initiators))
        else:
            return list_initiators

    def _get_mapped_initiators_on_same_level(self, container, remove_duplicate=True):
        """
        Returns a list of all the controllers for which this controller is the responder.

        :param container: The container object
        :return: List of mapped initiators
        """
        list_initiators = self._get_mapped_initiators(container, remove_duplicate)
        self_level = container.controller.loc[container.controller.object == self].level.values[0]

        list_initiators = [initiator for initiator in list_initiators if container.controller.loc[container.controller.object == initiator].level.values[0] == self_level]

        return list_initiators

    def _unapply_initiators(self, container):
        """
        Unapply all the controllers for which this controller is the responder.

        :param container: The container object
        """
        # Recursive unapply all the controllers for which this controller is the responder at the same level
        # so they will be re-executed
        # FixMe: level can be an array, use 'in' instead
        for initiator in self._get_mapped_initiators(container):
            initiator_level = container.controller.loc[container.controller.object == initiator].level.values[0]
            self_level = container.controller.loc[container.controller.object == self].level.values[0]
            if initiator_level == self_level and initiator.applied:
                initiator.applied = False
                for initiator_initiator in initiator._get_mapped_initiators(container):
                    initiator_initiator_level = container.controller.loc[container.controller.object == initiator_initiator].level.values[0]
                    if initiator_initiator_level == initiator_level:
                        initiator.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: np.nan,
                                                               FluidMixMapping.MASS_FLOW_KEY: np.nan}
                initiator._unapply_initiators(container)
                initiator._unapply_responders(container)

    def _unapply_responders(self, container):
        """
        Unapply all the controllers for which this controller is the initiator.

        :param container: The container object
        """
        # Recursive unapply all the controllers for which this controller is the initiator
        # so they will be re-executed
        for responder in self._get_mapped_responders(container):
            responder_level = container.controller.loc[container.controller.object == responder].level.values[0]
            self_level = container.controller.loc[container.controller.object == self].level.values[0]
            if responder_level == self_level and responder.applied:
                responder.applied = False
                responder.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: np.nan,
                                                       FluidMixMapping.MASS_FLOW_KEY: np.nan}
                responder._unapply_initiators(container)
                responder._unapply_responders(container)

    def _are_initiators_converged(self, prosumer):
        """
        Check if all the controllers for which this controller is the responder are converged.
        Return True if the controller has no initiator
        # ToDo: check if same level

        :param prosumer: The prosumer object
        :return: True if all the controllers are converged, False otherwise
        """
        for initiator in self._get_mapped_initiators(prosumer):
            if not initiator.is_converged(prosumer):
                return False
        return True
        
    def time_step(self, container, time):
        """
        Executes the time step for the controller.

        :param container: The container object
        :param time: The current time step
        """
        super().time_step(container, time)
        self.time = time
        self.step_results = np.full([1, len(self.result_columns)], np.nan)
        self.applied = False

    def control_step(self, container):
        """
        Executes the control step for the controller.

        :param container: The container object
        """
        super().control_step(container)

    def finalize_control(self, container):
        """
        Finalizes the step for the controller.

        :param container: The container object
        :param time: The current time step
        """
        super().finalize_control(container)
        self.inputs = np.full([self._nb_elements, len(self.input_columns)], np.nan)
        self.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: np.nan,
                                          FluidMixMapping.MASS_FLOW_KEY: np.nan}
        self.t_previous_return_out_c = np.nan
        self.t_previous_feed_in_c = np.nan
        self.mdot_previous_feed_kg_per_s = np.nan

    def time_series_initialization(self, container):
        """
        Initializes the time series for the controller.

        :param container: The prosumer/net/energy_system object
        :return: List of initializations
        """
        return []

    def time_series_finalization(self, container):
        """
        Finalizes the time series for the controller.

        :param container: The container object
        :return: List of finalizations
        """
        if self.has_period:
            return self.res
        else:
            return []
        
    def repair_control(self, container):
        super().repair_control(container)

    def restore_init_state(self, container):
        super().restore_init_state(container)

    def initialize_control(self, container):
        if getattr(container, "check_order", False): self.check_levels(container)
        super().initialize_control(container)
        
    def finalize_step(self, container, time):
        super().finalize_step(container, time)

    def set_active(self, container, in_service):
        super().set_active(container, in_service)

    def _merit_order_mass_flow(self, container, mdot_out_available_kg_per_s, mdot_required_tab_kg_per_s):
        """
        Implement a merit order logic: the first mapped element is served first
        and the second one get the remaining power (if there are two mapped controllers)

        :param container: The container object
        :param mdot_out_available_kg_per_s: The total mass flow available at the element output
        :param mdot_required_tab_kg_per_s: The list of the mass flows required by the mapped controllers

        :return mdot_res_tab_kg_per_s: The list of the mass flows delivered to the mapped controllers
        """

        mdot_res_tab_kg_per_s = []
        mdot_still_to_delivered_kg_per_s = mdot_out_available_kg_per_s
        # responders = self._get_mapped_responders(container, remove_duplicate=True)
        for mdot_required_responder_i_kg_per_s in mdot_required_tab_kg_per_s:
            mdot_delivered_responder_i_kg_per_s = np.minimum(mdot_required_responder_i_kg_per_s,
                                                             mdot_still_to_delivered_kg_per_s)
            mdot_res_tab_kg_per_s.append(mdot_delivered_responder_i_kg_per_s)
            mdot_still_to_delivered_kg_per_s -= mdot_delivered_responder_i_kg_per_s
        return mdot_res_tab_kg_per_s
    
    def finalize(self, container, result, result_fluid_mix=None):
        """
        Function that should be called at the end of the control step of the controllers.
        Write the results of the controller in the result columns for mapping to other responder controllers
        and saving in result history to export to timeseries result data frame

        :param container: The container (prosumer) object
        :param result: The results of the controller
        :param result_fluid_mix: The fluid mixture model (list of dictionaries)
        """
        if len(result):
            if np.isnan(result).any():  # Check that no result is empty
                nan_indexes = np.where(np.isnan(result))[1]
                nan_columns = [self.result_columns[i] for i in nan_indexes]
                raise ValueError(f"Result contains NaN values for controller '{self.name}' in prosumer "
                                 f"'{container.name}' at timestep '{self.time}' for column.s {nan_columns}")
            # Write the result in step_results for GenericMapping
            self.step_results = result
            # Write the result in res tab for saving to timeseries result data frame
            if self.has_period:
                time_step_idx = np.where(self.time_index == self.time)[0][0]
                self.res[:, time_step_idx, :] = result
        # Write result_fluid_mix for FluidMixMapping
        self.result_mass_flow_with_temp = result_fluid_mix

        # Execute all the mappings for which this controller is the initiator
        for row in self._get_mappings(container):
            if row.object.responder_net == container:
                if container.check_order: self.check_mappings_orders(container)
                row.object.map(self, container.controller.loc[row.responder].object)
            else:
                row.object.map(self, row.responder)

        # # Empty the inputs columns to prepare next time step
        # self.inputs = np.full([self._nb_elements, len(self.input_columns)], np.nan)
        # self.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: np.nan,
        #                                   FluidMixMapping.MASS_FLOW_KEY: np.nan}

    def check_levels(self, container):
        """
        Check that all controllers in the prosumer have the same level, except for controllers of type
        ConstProfile (which are allowed to be executed first).

        Raises:
            ValueError: If there is more than one level among controllers.
        """
        levels = []
        model = ["dry_cooler_controller","electric_boiler_controller","gas_boiler_controller",
                 "heat_demand_controller",'heat_exchanger_controller','heat_pump_controller',
                 'stratified_heat_storage_controller']
        for _, ctrl_row in container.controller.iterrows():
            ctrl = ctrl_row.object
            if ctrl.name in model:
                levels.append(ctrl.level)
        if levels and not all(l == levels[0] for l in levels):
            raise ValueError(
                f"Level error: Not all controllers have the same level (excluding ConstProfile). "
                f"Found levels: {set(levels)}."
            )


    def check_mappings_orders(self,container):
            """
            For each initiator in FluidMixMappings, check that the mapping orders are unique and form
            a consecutive sequence of integers starting from 0.

            Raises:
                ValueError: If the order numbers for any initiator are not consecutive.
            """
            filtered_mapping = container.mapping[container.mapping["object"].apply(lambda obj: obj.name == "FluidMixMapping")]
            grouped = filtered_mapping.groupby("initiator")
            for initiator, group in grouped:
                initiator_name = container.controller.iloc[initiator].object.name
                sorted_orders = sorted(group["order"].tolist())
                expected_orders = list(range(len(sorted_orders)))
                if sorted_orders != expected_orders:
                    raise ValueError(
                        f"Mapping order error: For initiator '{initiator_name}', the mapping orders {sorted_orders} "
                        f"are not consecutive integers starting at 0 (expected: {expected_orders})."
                    )