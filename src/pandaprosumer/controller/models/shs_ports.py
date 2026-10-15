"""
Stratified heat storage with its charge / discharge connections at any height.

A real tank is rarely a pipe in at the top and a pipe out at the bottom: it has nozzles at several heights
(space heating drawn half-way up, a lukewarm return sent to the middle so it does not stir the cold bottom),
valves that pick a nozzle by temperature, or stratification lances that let an inflow rise or sink to the
layer of its own temperature. This module places the four connections of the storage on layers and moves
the layers' temperatures with flows that differ from one interface to the next.

Connections (layer 0 is the bottom, ``n - 1`` the top):

* ``charge_in`` -- the source's feed enters (default: top);
* ``charge_out`` -- the water returned to the source leaves (default: bottom);
* ``discharge_out`` -- the water sent to the demand leaves (default: top);
* ``discharge_in`` -- the demand's return enters (default: bottom).

Each is placed at a fixed height (``height_<port>_m``) or automatically (listed in ``auto_ports``):

* an inlet in ``auto`` enters the highest layer not warmer than its water (an ideal stratification lance:
  the water settles where it is buoyancy-neutral, the stratification above it is left alone);
* ``discharge_out`` in ``auto`` draws the lowest layer still at least at the demand's feed temperature (the
  hottest water is kept for later), the top when none is;
* ``charge_out`` in ``auto`` draws the coldest layer (the best return for a heat pump).
"""

import numpy as np
from numba import njit

PORTS = ("charge_in", "charge_out", "discharge_out", "discharge_in")
HEIGHT_PARAMS = {port: f"height_{port}_m" for port in PORTS}


def parse_auto_ports(value):
    """The set of ports placed automatically, from the ``auto_ports`` parameter (comma-separated)."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return frozenset()
    names = {name.strip() for name in str(value).replace(";", ",").split(",") if name.strip()}
    names -= {"None", "nan", "null"}
    unknown = names - set(PORTS)
    if unknown:
        raise ValueError(f"auto_ports: unknown connection(s) {sorted(unknown)}, expected some of {list(PORTS)}")
    return frozenset(names)


def layer_at_height(height_m, n_layers, dz_m, default):
    """The layer holding ``height_m`` (m above the bottom); ``default`` when no height is given."""
    if height_m is None or (isinstance(height_m, float) and np.isnan(height_m)):
        return default
    return int(min(n_layers - 1, max(0, np.floor(float(height_m) / dz_m))))


def auto_inlet_layer(layer_temps_c, t_in_c):
    """The highest layer not warmer than the inflow (the bottom when every layer is warmer)."""
    temps = np.asarray(layer_temps_c, dtype=float)
    colder = np.flatnonzero(temps <= t_in_c)
    return int(colder[-1]) if colder.size else 0


def auto_discharge_layer(layer_temps_c, t_feed_c):
    """The lowest layer still at least at the demand's feed (the hottest layer when none is)."""
    temps = np.asarray(layer_temps_c, dtype=float)
    warm = np.flatnonzero(temps >= t_feed_c)
    return int(warm[0]) if warm.size else int(np.argmax(temps))


def plug_order(n_layers, outlet, inlet):
    """
    Layers in the order a flow from ``inlet`` to ``outlet`` pushes them out of ``outlet``: the outlet
    layer first, then towards the inlet. The layers beyond the outlet (away from the inlet) are not
    flushed by this flow and are left out.
    """
    step = 1 if inlet >= outlet else -1
    return list(range(outlet, inlet + step, step))


@njit
def _superbee(r):
    return max(0., max(min(1., 2. * r), min(2., r)))


@njit
def ports_convection_step(layer_temps_c, charge_in, charge_out, discharge_out, discharge_in,
                          mdot_charge_kg_per_s, t_charge_c, mdot_discharge_kg_per_s, t_return_c,
                          t_ext_c, cp_j_per_kgk, rho_kg_per_m3, A_m2, dz_m, Sl_m2, S1_m2, SN_m2,
                          k_star_w_per_mk, U_w_per_m2k, U1_w_per_m2k, UN_w_per_m2k, dt_s):
    """
    One explicit step of the layers with the connections on any layer (conservative finite volumes).

    The mass flow through the interface above layer ``i`` (downwards positive) is what enters the layers
    above it minus what leaves them. Each interface carries its flow at a face temperature: the upwind
    layer's, corrected towards the downwind one by the superbee limiter (second order where the profile is
    smooth, first order at a front -- the scheme of ``tvd_convection_step``, interface by interface).
    Inflows enter at their own temperature, outflows leave at their layer's, so the heat the layers gain is
    exactly the heat the connections bring minus what they take, the wall losses and nothing else.
    """
    T = layer_temps_c
    n = T.size
    source_kg_per_s = np.zeros(n)
    source_heat_w_per_cp = np.zeros(n)  # kg/s · °C
    sink_kg_per_s = np.zeros(n)
    source_kg_per_s[charge_in] += mdot_charge_kg_per_s
    source_heat_w_per_cp[charge_in] += mdot_charge_kg_per_s * t_charge_c
    source_kg_per_s[discharge_in] += mdot_discharge_kg_per_s
    source_heat_w_per_cp[discharge_in] += mdot_discharge_kg_per_s * t_return_c
    sink_kg_per_s[charge_out] += mdot_charge_kg_per_s
    sink_kg_per_s[discharge_out] += mdot_discharge_kg_per_s

    # flow_down[i]: through the interface between layer i (below) and i + 1 (above), downwards positive
    flow_down = np.zeros(n - 1)
    above = 0.
    for i in range(n - 1, 0, -1):
        above += source_kg_per_s[i] - sink_kg_per_s[i]
        flow_down[i - 1] = above

    layer_mass_kg = rho_kg_per_m3 * A_m2 * dz_m
    face_flux = np.zeros(n - 1)  # kg/s · °C carried downwards through each interface
    for j in range(n - 1):
        f = flow_down[j]
        if f == 0.:
            continue
        if f > 0.:  # from layer j + 1 down into j
            up, down, upup = j + 1, j, j + 2
        else:  # from layer j up into j + 1
            up, down, upup = j, j + 1, j - 1
        t_face = T[up]
        if 0 <= upup < n:
            delta = T[down] - T[up]
            if abs(delta) > 1e-10:
                r = (T[up] - T[upup]) / delta
                courant = abs(f) * dt_s / layer_mass_kg
                t_face = T[up] + 0.5 * (1. - courant) * _superbee(r) * delta
        face_flux[j] = f * t_face

    k_over_dz = k_star_w_per_mk * A_m2 / dz_m
    new_t = np.empty(n)
    for i in range(n):
        heat_w = 0.
        if i == 0:
            heat_w += U1_w_per_m2k * S1_m2 * (t_ext_c - T[0]) + (4. / 3.) * k_over_dz * (T[1] - T[0])
        elif i == n - 1:
            heat_w += UN_w_per_m2k * SN_m2 * (t_ext_c - T[i]) - (4. / 3.) * k_over_dz * (T[i] - T[i - 1])
        else:
            heat_w += U_w_per_m2k * Sl_m2 * (t_ext_c - T[i]) + k_over_dz * (T[i + 1] - 2. * T[i] + T[i - 1])
        advected = source_heat_w_per_cp[i] - sink_kg_per_s[i] * T[i]
        if i < n - 1:
            advected += face_flux[i]  # the interface above brings its flow down into i
        if i > 0:
            advected -= face_flux[i - 1]  # the interface below takes its flow down out of i
        heat_w += cp_j_per_kgk * advected
        new_t[i] = T[i] + dt_s * heat_w / (layer_mass_kg * cp_j_per_kgk)
    return new_t


@njit
def ports_resolution_in_time(layer_temps_c, charge_in, charge_out, discharge_out, discharge_in,
                             mdot_charge_kg_per_s, t_charge_c, mdot_discharge_kg_per_s, t_return_c,
                             t_ext_c, cp_j_per_kgk, rho_kg_per_m3, A_m2, dz_m, Sl_m2, S1_m2, SN_m2,
                             k_star_w_per_mk, U_w_per_m2k, U1_w_per_m2k, UN_w_per_m2k, resol, max_dt_s):
    """``ports_convection_step`` repeated over sub-steps of at most ``max_dt_s`` (as tvd_resolution_in_time)."""
    if resol < max_dt_s:
        nb_intervals = 1
        dt_s = resol
    else:
        offset = 1 if resol // max_dt_s != resol / max_dt_s else 0
        nb_intervals = int(resol // max_dt_s + offset)
        dt_s = resol / nb_intervals
    for _ in range(nb_intervals):
        layer_temps_c = ports_convection_step(layer_temps_c, charge_in, charge_out, discharge_out, discharge_in,
                                              mdot_charge_kg_per_s, t_charge_c, mdot_discharge_kg_per_s, t_return_c,
                                              t_ext_c, cp_j_per_kgk, rho_kg_per_m3, A_m2, dz_m, Sl_m2, S1_m2, SN_m2,
                                              k_star_w_per_mk, U_w_per_m2k, U1_w_per_m2k, UN_w_per_m2k, dt_s)
    return layer_temps_c
