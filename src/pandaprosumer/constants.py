from pandapipes.constants import *

CELSIUS_TO_K = NORMAL_TEMPERATURE
TEMPERATURE_CONVERGENCE_THRESHOLD_C = 0.01
# Latent heat of vaporization of water at ~30°C [J/kg], for adiabatic cooler water consumption
LATENT_HEAT_VAPORIZATION_WATER_J_PER_KG = 2430e3
MAX_RERUN = 20


class HeatExchangerControl:
    OUT_OF_RANGE_THRESHOLD = 36.5
    MIN_PRIMARY_MASS_FLOW_KG_PER_S = 0.05555556
    # Cold-side approach [K] used when the secondary inlet is too warm for min_delta_t_1_c: the primary outlet is then
    # set this much above the secondary inlet (or the exchanger stalls if even that cannot cool the primary)
    MIN_DELTA_T_COLD_C = 3
    DICHOTOMY_CONVERGENCE_THRESHOLD = 1e-12
