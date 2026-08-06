from dataclasses import dataclass, field


@dataclass
class ElectricalOptimizationControllerData:
    element_name: str = "electrical_optimization"
    element_index: list = field(default_factory=list)
    period_index: int = 0

    input_columns: list = field(
        default_factory=lambda: [
            "p_el_demand_kw",
            "p_pv_in_kw",
            "p_contract_kw",
            "p_flex_kw",
            "p_grid_target_kw",
            "electricity_price_eur_per_mwh",
            "gas_price_eur_per_mwh"
        ]
    )

    result_columns: list = field(
        default_factory=lambda: [
            "p_battery_kw",
            "p_el_chp_kw",
        ]
    )