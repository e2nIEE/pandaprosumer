from dataclasses import dataclass
from dataclasses import field
from typing import List, Callable

from pandaprosumer.element.element_toolbox import enforce_types


@enforce_types
@dataclass
class ChillerControllerData:
    """Define format of I/O of a chiller in SenergyNets"""

    element_index: List[int]
    period_index: int = None
    element_name: str = 'sn_chiller'
    input_columns: List[str] = field(default_factory=lambda: ["t_set_pt_c", "t_in_ev_c", "t_in_cond_c", "dt_cond_c", "q_load_kw", "n_is", "q_max_kw", "ctrl"])

    result_columns: List[str] = field(
        default_factory=lambda: [
            "q_evap_kw",
            "unmet_load_kw",
            "w_in_tot_kw", #faltan unidades
            "eer",
            "plr",
            "t_out_ev_in_c",
            "t_out_cond_in_c",
            "m_evap_kg_per_s",
            "m_cond_kg_per_s",
            "q_cond_kw",
        ]
    )

