import numpy as np
import logging

from pandaprosumer.constants import HeatExchangerControl

logger = logging.getLogger(__name__)


def solve_dichotomy(f, x_min, x_max, is_increasing=True):
    """
    Solve f(x)=0 by dichotomy in the interval [x_min, x_max].

    :param f: Function to be solved.
    :param x_min: Minimum value.
    :param x_max: Maximum value.
    :param is_increasing: Boolean indicating if the function is strictly increasing (dry cooler).
                          If False, the function is assumed to be strictly decreasing (heat exchanger).
    :return: The found value of x after convergence.
    """
    x_mean = (x_max + x_min) / 2
    nb_runs = 0
    while (abs(f(x_mean)) > HeatExchangerControl.DICHOTOMY_CONVERGENCE_THRESHOLD
           and abs(x_max - x_min) > HeatExchangerControl.DICHOTOMY_CONVERGENCE_THRESHOLD):
        nb_runs += 1
        if nb_runs > 300:
            logger.warning(f"Dichotomy did not converge after {nb_runs} runs."
                           f"Reached xmin={x_min}, xmax={x_max}. Continuing with x_mean={x_mean}")
            break
        x_mean = (x_max + x_min) / 2
        if (is_increasing and f(x_mean) < 0) or (not is_increasing and f(x_mean) > 0):
            x_min = x_mean
        else:
            x_max = x_mean
    return x_mean


def calculate_temperature_difference(a, delta_t, is_cold=True):
    """
    Solve the equation with dichotomy to find the temperature difference.

    :param a: The parameter 'a'.
    :param delta_t: The temperature difference between the primary and secondary temperatures.
    :param is_cold: Boolean indicating if calculating cold temperature difference (heat_exchanger).
                    If False, calculates hot temperature difference (dry cooler.
    :return: The temperature difference between the primary and secondary temperatures.
    """
    if is_cold:
        dichotomy_fun = lambda x: a * x + np.log(1 - x)  # if (1 - x) > 0 else float('inf')
        if a > 1:
            # dichotomy_fun is strictly decreasing on [x_min, x_max], 0 < x < 1
            x_max = 1
            x_min = (a - 1) / (a - 0.001)
        else:
            # dichotomy_fun is strictly increasing on [x_max, x_min], x < 0
            x_max = (a - 1) / a
            x_min = 3 * x_max

        x_mean = solve_dichotomy(dichotomy_fun, x_min, x_max, is_increasing=False)
        return (1 - x_mean) * delta_t
    else:
        dichotomy_fun = lambda x: a * x - np.log(1 + x) if (1 + x) > 0 else float('inf')
        if a > 1:
            # dichotomy_fun is strictly decreasing on [x_max, x_min], -1 < x < 0
            x_max = -1
            x_min = (1 - a) / (a - 0.001)
        else:
            # dichotomy_fun is strictly increasing on [x_min, x_max], x > 0
            x_min = max((1 - a) / (a - 0.001), -0.999)
            x_max = 3 * x_min
        x_mean = solve_dichotomy(dichotomy_fun, x_min, x_max)
        return (1 + x_mean) * delta_t


def compute_temp(q_ratio, q_u_w, t_in_c, t_fluid_in_c, t_fluid_out_c,
                 delta_t_hot_n, delta_t_cold_n, cp_j_per_kgk, heat_consumer=True):
    """
    Calculate the return temperature and the mass flow rate.

    :param q_ratio: The ratio of the exchanged heat and the nominal exchanged heat.
    :param q_u_w: The heat to be exchanged.
    :param t_in_c: The input temperature (primary or air).
    :param t_fluid_in_c: The fluid input temperature (hot for primary, cold for air).
    :param t_fluid_out_c: The fluid output temperature (cold for primary, hot for air).
    :param delta_t_hot_n: The nominal temperature difference (hot).
    :param delta_t_cold_n: The nominal temperature difference (cold).
    :param cp_j_per_kgk: The heat capacity of the fluid or air.
    :param heat_consumer: Boolean indicating if calculating for heat consumption.
                      If False, calculates for heat production.
    :return: The return temperature and the mass flow rate.
    """

    if q_ratio == 0:
        # No heat transfer at the secondary side so no heat transfer at the primary side
        t_out_c = t_in_c
    else:
        delta_t = t_fluid_out_c - t_in_c if heat_consumer else t_in_c - t_fluid_out_c
        # Logarithmic mean temperature difference (LMTD) at nominal conditions
        # if delta_t_hot_n == delta_t_cold_n ? wikipedia: limit val: lmtd_n = delta_t_hot_n = delta_t_cold_n
        if delta_t_hot_n == delta_t_cold_n and heat_consumer:
            lmtd_n = delta_t_cold_n
        elif delta_t_hot_n == delta_t_cold_n and not heat_consumer:
            lmtd_n = delta_t_hot_n
        else:
            lmtd_n = (delta_t_hot_n - delta_t_cold_n) / np.log(delta_t_hot_n / delta_t_cold_n)
        a = delta_t / (q_ratio * lmtd_n)

        if a > HeatExchangerControl.OUT_OF_RANGE_THRESHOLD:
            logger.warning(f"Heat Exchanger state too far from nominal conditions. "
                           f"The temperature difference between the primary (t_in_c={t_in_c}°C) and "
                           f"secondary side (t_fluid_out_c={t_fluid_out_c}°C) may be too high or the transferred heat "
                           f"q_u_w={q_u_w}W too small compared to the nominal conditions")
            t_out_c = t_in_c
        else:
            delta_t_result = calculate_temperature_difference(a, delta_t, is_cold=not heat_consumer)
            t_out_c = t_fluid_in_c - delta_t_result if heat_consumer else t_fluid_in_c + delta_t_result
    # Find the primary mass flow rate so that the heat exchanged by the fluid on the primary side is equal to q_u
    # mdot_1_kg_per_s = q_u_w / (cp_1_j_per_kgk * (t_1_in_c - t_1_out_c))
    # mdot_air_kg_per_s = q_u_w / (cp_air_j_per_kgk * (t_air_out_c - t_air_in_c))
    if t_out_c == t_in_c or (t_out_c < t_in_c and heat_consumer):
        mdot_kg_per_s = 0

    elif t_out_c > t_in_c and not heat_consumer:
        t_out_c = t_in_c
        mdot_kg_per_s = 0
    # elif a == 0:  # Note: Can go there with 'a' not defined if T_in_1 is nan
    #     mdot_kg_per_s = HeatExchangerControl.MIN_PRIMARY_MASS_FLOW_KG_PER_S  # 0.2 m3/h  FixMe: Why ?
    else:
        mdot_kg_per_s = q_u_w / (cp_j_per_kgk * abs(t_in_c - t_out_c))

    # self._a = a

    return t_out_c, mdot_kg_per_s
