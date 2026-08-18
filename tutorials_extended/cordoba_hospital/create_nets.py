import pandapipes as ppi

import pandapipes as ppi


def create_thermal_networks():

    net_cold = ppi.create_empty_network(fluid="water")

    # Knoten (Junctions)
    j_c_supply = ppi.create_junction(net_cold, pn_bar=4, tfluid_k=283.15, name="Cold Supply (Erzeuger)")
    j_c_return = ppi.create_junction(net_cold, pn_bar=4, tfluid_k=288.15, name="Cold Return (Erzeuger)")

    j_c_cons_in = ppi.create_junction(net_cold, pn_bar=4, tfluid_k=283.15, name="Cold Consumer Inlet")
    j_c_cons_mid = ppi.create_junction(net_cold, pn_bar=4, tfluid_k=283.15, name="Cold Consumer Mid")
    j_c_cons_out = ppi.create_junction(net_cold, pn_bar=4, tfluid_k=288.15, name="Cold Consumer Outlet")

    # Rohre
    ppi.create_pipe(net_cold, from_junction=j_c_supply, to_junction=j_c_cons_in,
                    length_km=1.5, k_mm=0.1, name="Cold Pipe Supply", std_type="280_PE-HD_16")
    ppi.create_pipe(net_cold, from_junction=j_c_cons_out, to_junction=j_c_return,
                    length_km=1.5, k_mm=0.1, name="Cold Pipe Return", std_type="280_PE-HD_16")

    # Massenstrom aus qext_w und Temperaturen berechnen
    # qext_w = 1000000 W (Wärmezufuhr ins Netz = Kälteentnahme)
    # delta_T = 15°C - 10°C = 5 K
    # cp = 4182 J/kgK
    mdot_cold = 1000000 / (4182 * 5.0)  # ca. 47.8 kg/s

    ppi.create_circ_pump_const_pressure(net_cold, return_junction=j_c_return, flow_junction=j_c_supply,
                                        p_flow_bar=3, plift_bar=2, t_flow_k=283.15, name="pump_hp_coupling")


    # Verbraucher: Heat Exchanger statt Heat Consumer
    ppi.create_flow_control(net_cold, from_junction=j_c_cons_in, to_junction=j_c_cons_in,
                            controlled_mdot_kg_per_s=mdot_cold)
    # qext_w ist HIER positiv, da dem Kältekreislauf Wärme zugeführt wird!
    ppi.create_heat_exchanger(net_cold, from_junction=j_c_cons_mid, to_junction=j_c_cons_out,
                              qext_w=1000000,
                              name="Hospital Cooling Demand (1 MW)")

    # ==========================================
    # 2. Heizkreis (Hot Loop) - Winter: 78/70 °C
    # ==========================================
    net_hot = ppi.create_empty_network(fluid="water")

    # Knoten (Junctions)
    # Erzeuger-Seite (Vorlauf 78°C / Rücklauf 70°C)
    j_h_supply = ppi.create_junction(net_hot, pn_bar=6, tfluid_k=320.15, name="Hot Supply (Erzeuger)")  # 78°C
    j_h_return = ppi.create_junction(net_hot, pn_bar=6, tfluid_k=320.15, name="Hot Return (Erzeuger)")  # 70°C

    j_h_cons_in = ppi.create_junction(net_hot, pn_bar=6, tfluid_k=320.15, name="Hot Consumer Inlet")
    j_h_cons_out = ppi.create_junction(net_hot, pn_bar=6, tfluid_k=320.15, name="Hot Consumer Outlet")

    # Rohre (1.5 km laut Dokument)
    ppi.create_pipe(net_hot, from_junction=j_h_supply, to_junction=j_h_cons_in,
                    length_km=1.5,  k_mm=0.1, text_k=273.15, name="Hot Pipe Supply", std_type="280_PE-HD_16")
    ppi.create_pipe(net_hot, from_junction=j_h_cons_out, to_junction=j_h_return,
                    length_km=1.5,  k_mm=0.1, text_k=273.15, name="Hot Pipe Return", std_type="280_PE-HD_16")

    # Erzeuger: Umwälzpumpe mit Drucksteuerung (circ_pump_pressure)
    ppi.create_circ_pump_const_pressure(net_hot, return_junction=j_h_return, flow_junction=j_h_supply,
                                  p_flow_bar=16, plift_bar=8, t_flow_k=352.15, name='pump_hp_coupling')

    # Verbraucher: Heat Consumer
    # Vorgabe von qext_w (Heizbedarf, also Wärmeentzug aus dem Netz -> positiv) und treturn_k (70°C = 343.15 K)
    ppi.create_heat_consumer(net_hot, from_junction=j_h_cons_in, to_junction=j_h_cons_out,
                             qext_w=800000, deltat_k=8, #treturn_k=343.15,
                             name='heat_consumer_demand_coupling')

    net_hot.pipe["u_w_per_m2k"] = 0.1

    # DHW Speicher (25 m³ laut Dokument) vereinfacht als Junction mit großem Volumen
    # j_tes = ppi.create_junction(net_hot, pn_bar=6, tfluid_k=333.15, name="DHW Storage (25m3)")
    # # Kurze Anbindung an den Rücklauf
    # ppi.create_pipe(net_hot, from_junction=j_h_return, to_junction=j_tes,
    #                 length_km=0.05, diameter_m=0.15, name="DHW Storage Connection")

    return net_cold, net_hot


if __name__ == "__main__":
    net_cold, net_hot = create_thermal_networks()


    # Optional: Pipeflow testen
    ppi.pipeflow(net_hot)
    ppi.pipeflow(net_cold)
