from pandapipes.constants import *

CELSIUS_TO_K = NORMAL_TEMPERATURE
# Acceptance tolerance (K) for the iterative FluidMix return-temperature
# reconciliation shared by every controller's reapply loop (HX, HP, dry cooler,
# heat demand, stratified storage, pandapipes connector). A responder hands its
# initiator a return-temperature contract (``t_keep_return_c``); after running,
# it recomputes its own return and reapplies the initiator until the two agree
# to within this band. At the historic 1 K the residual gap, times mdot*cp, left
# a cross-container energy-conservation error of tens of kW at ECS charge flows
# (source q != SHS q_received). Tightened to 1e-2 K so the loop actually drives
# the two returns together and the exchanged energy is conserved by the
# iteration itself. Per-controller stagnation guards still bound the loop when a
# fixed point is genuinely irreconcilable, so this does not risk non-convergence.
TEMPERATURE_CONVERGENCE_THRESHOLD_C = 1e-2
# Latent heat of vaporization of water at ~30°C [J/kg], for adiabatic cooler water consumption
LATENT_HEAT_VAPORIZATION_WATER_J_PER_KG = 2430e3
MAX_RERUN = 20


class HeatExchangerControl:
    OUT_OF_RANGE_THRESHOLD = 36.5
    MIN_PRIMARY_MASS_FLOW_KG_PER_S = 0.05555556
    DICHOTOMY_CONVERGENCE_THRESHOLD = 1e-12
