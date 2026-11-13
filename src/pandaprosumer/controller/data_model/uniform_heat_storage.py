from dataclasses import dataclass, field
from typing import List
from pandaprosumer.element.element_toolbox import enforce_types


@enforce_types
@dataclass
class UniformHeatStorageControllerData:
    """
    Data class for the uniform (fully mixed) heat storage controller.

    Attributes
    ----------
    element_index : List[int]
        List of element indices.
    element_name : str
        Name of the element.
    period_index : int, optional
        Index of the period, default is None.
    input_columns : List[str]
        List of input column names. Both inputs are optional external dispatch setpoints. NaN (not mapped)
        or a negative value means "no setpoint": the storage's own charge/discharge logic applies for that
        timestep. ``0.0`` is a setpoint (force no charge / no discharge).

        **mdot_charge_setpoint_kg_per_s** - Imposed charge mass flow. Clamped to the mass flow actually
        received from upstream and ignored when the tank is full [kg/s].

        **mdot_discharge_setpoint_kg_per_s** - Imposed discharge mass flow. Clamped to zero when the tank is
        not warmer than the demand return temperature [kg/s].

    result_columns : List[str]
        List of result column names. The first eighteen are the ones of the stratified heat storage: four
        flows (received, charge, discharge, delivered), each as (mdot, t_in, t_out, q), then the stored and
        usable energy:

        **mdot_received_kg_per_s / t_received_in_c / t_received_out_c / q_received_kw** - Fluid received
        from upstream initiators and the heat the storage took from it [kg/s, °C, °C, kW].

        **mdot_charge_kg_per_s / t_charge_in_c / t_charge_out_c / q_charge_kw** - Part of the received fluid
        that goes through the tank (the rest is bypassed to the demand). ``t_charge_out_c`` is the mean
        temperature of the water the tank gave back over the step [kg/s, °C, °C, kW].

        **mdot_discharge_kg_per_s / t_discharge_in_c / t_discharge_out_c / q_discharge_kw** - Fluid drawn
        from the tank for the demand. ``t_discharge_in_c`` is the demand return, ``t_discharge_out_c`` the
        mean tank temperature over the step [kg/s, °C, °C, kW].

        **mdot_delivered_kg_per_s / t_delivered_in_c / t_delivered_out_c / q_delivered_kw** - Total fluid
        sent to the demand (discharge + bypass mixed) [kg/s, °C, °C, kW].

        **e_stored_kwh** - Heat stored compared to the initial tank temperature (negative when the tank is
        colder than it started) [kWh]

        **e_usable_kwh** - Heat the demand can still draw: the tank's heat above the demand return while the
        tank is not colder than ``min_useful_temp_c`` (minus 0.5 K), 0 otherwise [kWh]

        **t_tank_c** - Tank temperature at the end of the step [°C]

        **q_loss_kw** - Mean heat lost through the wall over the step [kW]
    """
    element_index: List[int]
    element_name: str = 'uniform_heat_storage'
    period_index: int = None
    input_columns: List[str] = field(default_factory=lambda: ["mdot_charge_setpoint_kg_per_s",
                                                              "mdot_discharge_setpoint_kg_per_s"])
    result_columns: List[str] = field(default_factory=lambda: [
        "mdot_received_kg_per_s", "t_received_in_c", "t_received_out_c", "q_received_kw",
        "mdot_charge_kg_per_s", "t_charge_in_c", "t_charge_out_c", "q_charge_kw",
        "mdot_discharge_kg_per_s", "t_discharge_in_c", "t_discharge_out_c", "q_discharge_kw",
        "mdot_delivered_kg_per_s", "t_delivered_in_c", "t_delivered_out_c", "q_delivered_kw",
        "e_stored_kwh", "e_usable_kwh",
        "t_tank_c", "q_loss_kw",
    ])
