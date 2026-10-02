import numpy as np
from pandaprosumer.mapping.fluid_mix import FluidMixMapping
from pandaprosumer.controller.base import BasicProsumerController
from pandaprosumer.controller.models.heat_pump import HeatPumpController
from pandaprosumer.constants import CELSIUS_TO_K, TEMPERATURE_CONVERGENCE_THRESHOLD_C

class CoupledHeatPumpController(HeatPumpController):

    def name_class(self):
        return "coupled_heat_pump_controller"

    def __init__(
            self,
            prosumer,
            heat_pump_object,
            order,
            level,
            in_service=True,
            index=None,
            name=None,
            **kwargs
    ):
        super().__init__(
            prosumer=prosumer,
            heat_pump_object=heat_pump_object,
            order=order,
            level=level,
            in_service=in_service,
            index=index,
            name=name,
            **kwargs
        )
        # Mapping-order aus FluidMixEnergySystemMapping (siehe result_fluid_mix)
        self._MAPPING_ORDER_COND = 0
        self._MAPPING_ORDER_EVAP = 1

    @property
    def _t_evap_in_c(self):
        return self._get_input("t_evap_in_c")

    @property
    def _t_cond_in_c(self):
        return self._get_input("t_cond_in_c")

    @property
    def _t_cond_out_c(self):
        return self._get_input("t_cond_out_c")

    # --- unverändert: Mapping-Split über die Spalte "order" -----------------------
    def _get_mapped_responders_by_order(self, container, order, remove_duplicate=True):
        mask_initiator = container.mapping["initiator"] == self.index
        mask_no_chain = ~container.mapping["object"].apply(lambda r: r.no_chain)
        mask_order = container.mapping["order"] == order

        filtered_mapping = (
            container.mapping[mask_initiator & mask_no_chain & mask_order]
            .sort_values("order")
            [["object", "responder"]]
        )

        list_responders = [
            obj.responder_net.controller.loc[responder]["object"]
            for obj, responder in filtered_mapping.itertuples(index=False)
        ]

        if remove_duplicate:
            return list(dict.fromkeys(list_responders))
        return list_responders

    def _get_mapped_responders_cond(self, container, remove_duplicate=True):
        return self._get_mapped_responders_by_order(container, self._MAPPING_ORDER_COND, remove_duplicate)

    def _get_mapped_responders_evap(self, container, remove_duplicate=True):
        return self._get_mapped_responders_by_order(container, self._MAPPING_ORDER_EVAP, remove_duplicate)

    # _get_mapped_responders_cond_evap kann weg. Falls der Name noch irgendwo
    # gebraucht wird, reicht ein dünner Wrapper:
    # def _get_mapped_responders_cond_evap(self, prosumer):
    #     return self._get_mapped_responders_cond(prosumer), self._get_mapped_responders_evap(prosumer)

    # --- angepasst: Richtung (max/min) über Parameter steuerbar -------------------
    def _t_m_to_deliver_side(self, prosumer, responders, colder_is_worse=False):
        if len(responders) == 0:
            return 0, 0, np.array([])

        tfeed_tab_c, treturn_tab_c, mdot_tab_kg_per_s = np.array([]), np.array([]), np.array([])
        for responder in responders:
            container = self._resolve_responder_container(prosumer, responder)
            tfeed_i, treturn_i, mdot_i = responder.t_m_to_receive(container)
            tfeed_tab_c = np.append(tfeed_tab_c, tfeed_i)
            treturn_tab_c = np.append(treturn_tab_c, treturn_i)
            mdot_tab_kg_per_s = np.append(mdot_tab_kg_per_s, mdot_i)

        tfeed_res_c = min(tfeed_tab_c) if colder_is_worse else max(tfeed_tab_c)
        delta_t_c = np.full(len(treturn_tab_c), tfeed_res_c) - treturn_tab_c
        valid_delta_t_c = np.where(delta_t_c != 0, delta_t_c, np.nan)
        mdot_tab_temp_kg_per_s = mdot_tab_kg_per_s * (tfeed_tab_c - treturn_tab_c) / valid_delta_t_c
        mdot_tab_updated_kg_per_s = np.where(np.isnan(mdot_tab_temp_kg_per_s), 0, mdot_tab_temp_kg_per_s)

        mdot_kg_per_s = np.sum(mdot_tab_updated_kg_per_s)
        treturn_res_c = (
            np.sum(mdot_tab_updated_kg_per_s * treturn_tab_c) / mdot_kg_per_s
            if abs(mdot_kg_per_s) > 1e-8 else tfeed_res_c
        )
        return tfeed_res_c, treturn_res_c, mdot_tab_updated_kg_per_s

    def t_m_to_deliver(self, prosumer):
        """Nur kondensatorseitige Responder (order=0). Referenz = höchste Temperatur."""
        cond_responders = self._get_mapped_responders_cond(prosumer)
        return self._t_m_to_deliver_side(prosumer, cond_responders, colder_is_worse=False)

    def t_m_to_deliver_evap(self, prosumer):
        """Nur verdampferseitige Responder (order=1). Referenz = niedrigste Temperatur."""
        evap_responders = self._get_mapped_responders_evap(prosumer)
        return self._t_m_to_deliver_side(prosumer, evap_responders, colder_is_worse=True)

    def _resolve_responder_container(self, prosumer, responder):
        """
        Liefert den Container (prosumer oder gemapptes Netz), in dem 'responder'
        liegt. Notwendig, weil z.B. NetworkCouplingController-Responder ein
        pandapipes-Netz statt den prosumer-Container erwarten.
        """
        same_container = any(
            controller_row.object == responder
            for _, controller_row in prosumer.controller.iterrows()
        )
        if same_container:
            return prosumer

        for _, mapping_row in prosumer.mapping.iterrows():
            for _, controller_row in mapping_row.object.responder_net.controller.iterrows():
                if controller_row.object == responder:
                    return mapping_row.object.responder_net
        return prosumer  # Fallback, sollte nicht vorkommen

    def _get_treturn_tab_c_side(self, prosumer, responders):
        """Wie get_treturn_tab_c() der Basisklasse, aber für eine explizite
        Responder-Liste (cond ODER evap) und mit korrekter Container-Auflösung."""
        treturn_tab_c = np.array([])
        for responder in responders:
            container = self._resolve_responder_container(prosumer, responder)
            _, treturn_i, _ = responder.t_m_to_receive(container)
            treturn_tab_c = np.append(treturn_tab_c, treturn_i)
        return treturn_tab_c

    def get_treturn_tab_c_cond(self, prosumer):
        return self._get_treturn_tab_c_side(prosumer, self._get_mapped_responders_cond(prosumer))

    def get_treturn_tab_c_evap(self, prosumer):
        return self._get_treturn_tab_c_side(prosumer, self._get_mapped_responders_evap(prosumer))


    def control_step(self, prosumer):
        """
        Executes the control step for the controller.

        :param prosumer: The prosumer object
        """
        if not prosumer.rerun:
            self._save_state()
        else:
            self._restore_state()

        if not (self.in_service and getattr(prosumer, self.obj.element_name).iloc[self.obj.element_index[0]].in_service):
            self.applied = True
            return

        BasicProsumerController.control_step(self, prosumer)

        if not self._are_initiators_converged(prosumer):
            # If some of the initiators are not converged, do not run the control step
            self._unapply_initiators(prosumer)
            self.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: np.nan,
                                              FluidMixMapping.MASS_FLOW_KEY: np.nan}
            return

        # t_cond_out_required_c, t_cond_in_required_c, mdot_tab_required_kg_per_s = self.t_m_to_deliver(prosumer)
        # mdot_cond_required_kg_per_s = np.sum(mdot_tab_required_kg_per_s)
        # --- Beide Seiten getrennt abfragen (wärmegeführt: cond gibt den Takt vor) ---
        t_cond_out_required_c, t_cond_in_required_c, mdot_tab_required_kg_per_s = self.t_m_to_deliver(prosumer)

        if not np.isnan(self._t_cond_in_c):
            # Verbindliche Randbedingung aus dem heißen Netz:
            t_cond_in_required_c = self._t_cond_in_c

        # if not np.isnan(self._t_cond_out_c):
        #     # Verbindliche Randbedingung aus dem heißen Netz:
        #     t_cond_out_required_c = self._t_cond_out_c

        mdot_cond_required_kg_per_s = np.sum(mdot_tab_required_kg_per_s)

        t_evap_out_required_c, t_evap_in_expected_c, mdot_tab_evap_required_kg_per_s = self.t_m_to_deliver_evap(
            prosumer)
        mdot_evap_required_kg_per_s = np.sum(mdot_tab_evap_required_kg_per_s)
        # t_evap_in_expected_c aktuell nur informativ, siehe Annahme (2) unten

        assert not np.isnan(mdot_cond_required_kg_per_s), f"Heat Pump {self.name} mdot_cond_required_kg_per_s is NaN for timestep {self.time} in prosumer {prosumer.name}"
        assert not np.isnan(t_cond_out_required_c), f"Heat Pump {self.name} t_cond_out_required_c is NaN for timestep {self.time} in prosumer {prosumer.name}"
        assert not np.isnan(t_cond_in_required_c), f"Heat Pump {self.name} t_cond_in_required_c is NaN for timestep {self.time} in prosumer {prosumer.name}"
        assert not np.isnan(self._t_evap_in_c), f"Heat Pump {self.name} t_evap_in_c is NaN for timestep {self.time} in prosumer {prosumer.name}"
        assert t_cond_out_required_c >= t_cond_in_required_c, f"Heat Pump {self.name} t_cond_out_required_c < t_cond_in_required_c for timestep {self.time} in prosumer {prosumer.name}"
        assert mdot_cond_required_kg_per_s >= 0, f"Heat Pump {self.name} mdot_cond_kg_per_s is negative ({mdot_cond_required_kg_per_s}) for timestep {self.time} in prosumer {prosumer.name}"

        rerun = True
        while rerun:
            pinch_c = self._get_element_param(prosumer, 'pinch_c')

            (q_cond_kw, p_comp_kw, q_evap_kw, cop_hp,
             mdot_cond_kg_per_s, t_cond_in_c, t_cond_out_c,
             mdot_evap_kg_per_s, t_evap_in_c, t_evap_out_c) = self._calculate_heat_pump(prosumer,
                                                                                        mdot_cond_required_kg_per_s,
                                                                                        t_cond_out_required_c,
                                                                                        t_cond_in_required_c,
                                                                                        self._t_evap_in_c,
                                                                                        pinch_c)
            if not np.isnan(self._mdot_evap_in_kg_per_s):
                # If the evaporator is fed with a fixed mass flow (not free air)
                if mdot_evap_kg_per_s > self._mdot_evap_in_kg_per_s:
                    # If the evaporator mass flow is higher than the one required by the Heat Pump,
                    # recalculate the secondary mass flow to reduce the heat demand to reduce the evaporator mass flow
                    cp_evap_kj_per_kgk = self.evap_fluid.get_heat_capacity(CELSIUS_TO_K + (t_evap_in_c + t_evap_out_c) / 2) / 1000
                    cp_cond_kj_per_kgk = self.cond_fluid.get_heat_capacity(CELSIUS_TO_K + (t_cond_out_c + t_cond_in_c) / 2) / 1000
                    q_evap_kw = self._mdot_evap_in_kg_per_s * (cp_evap_kj_per_kgk * abs(t_evap_out_c - t_evap_in_c))
                    p_comp_kw = q_cond_kw - q_evap_kw
                    mdot_cond_kg_per_s = p_comp_kw * cop_hp / (cp_cond_kj_per_kgk * (t_cond_out_c - t_cond_in_c))

                    (q_cond_kw, p_comp_kw, q_evap_kw, cop_hp,
                     mdot_cond_kg_per_s, t_cond_in_c, t_cond_out_c,
                     mdot_evap_kg_per_s, t_evap_in_c, t_evap_out_c) = self._calculate_heat_pump_reverse(prosumer,
                                                                                                        self._mdot_evap_in_kg_per_s,
                                                                                                        self._t_evap_in_c,
                                                                                                        t_evap_out_c,
                                                                                                        t_cond_in_c,
                                                                                                        t_cond_out_c)
                elif mdot_evap_kg_per_s < self._mdot_evap_in_kg_per_s:
                    # If the evaporator mass flow is lower than the one required by the Heat Pump,
                    # model a bypass on the evaporator side where the extra mass flow doesn't exchange heat.
                    # Recalculate the evaporator output temperature
                    mdot_bypass_kg_per_s = self._mdot_evap_in_kg_per_s - mdot_evap_kg_per_s
                    t_bypass_c = t_evap_in_c
                    t_evap_out_c = (t_bypass_c * mdot_bypass_kg_per_s + t_evap_out_c * mdot_evap_kg_per_s) / self._mdot_evap_in_kg_per_s
                    mdot_evap_kg_per_s = self._mdot_evap_in_kg_per_s

            overflow_strategy = self._get_element_param(prosumer, 'overflow_strategy')
            if overflow_strategy is None or (isinstance(overflow_strategy, float) and np.isnan(overflow_strategy)):
                overflow_strategy = "cap"
            result_mdot_tab_kg_per_s = self._merit_order_mass_flow(prosumer,
                                                                   mdot_cond_kg_per_s,
                                                                   mdot_tab_required_kg_per_s,
                                                                   overflow_strategy=overflow_strategy)

            rerun = False
            if len(self._get_mapped_responders(prosumer)) > 1 and mdot_cond_kg_per_s < mdot_cond_required_kg_per_s:
                # FixMe: Can't test this case in a single model test without mapping (no responders)
                # If the heat Pump is not able to deliver the required mass flow,
                # recalculate the condenser input temperature, considering that all the downstream elements will be
                # still return the same temperature, even if the mass flow delivered to them by the Heat Pump is lower
                # t_return_tab_c = self.get_treturn_tab_c(prosumer)
                t_return_tab_c = self.get_treturn_tab_c_cond(prosumer)
                if abs(mdot_cond_kg_per_s) > 1e-8:
                    t_cond_in_new_c = np.sum(result_mdot_tab_kg_per_s * t_return_tab_c) / mdot_cond_kg_per_s
                else:
                    t_cond_in_new_c = t_cond_in_required_c
                if abs(t_cond_in_new_c - t_cond_in_required_c) > 1:
                    # If this recalculation changes the condenser input temperature, rerun the calculation
                    # with the new temperature
                    t_cond_in_required_c = t_cond_in_new_c
                    rerun = True

        # After merit-order capping, ensure mass and energy balance at the interface.
        # If the effective condenser mass flow differs from what the model used, re-run the
        # heat pump physics with the new mdot_cond so COP, p_comp, t_cond_out, etc. are consistent.
        mdot_used_kg_per_s = np.sum(result_mdot_tab_kg_per_s)
        tol = 1e-9
        mdot_cond_new = None
        if abs(mdot_cond_kg_per_s - mdot_used_kg_per_s) > tol:
            if mdot_used_kg_per_s > tol:
                mdot_cond_new = mdot_used_kg_per_s
            elif -tol < mdot_used_kg_per_s < tol and q_cond_kw > tol:
                cp_cond_kj_per_kgk = self.cond_fluid.get_heat_capacity(
                    CELSIUS_TO_K + (t_cond_out_c + t_cond_in_c) / 2
                ) / 1000
                mdot_cond_new = q_cond_kw / (cp_cond_kj_per_kgk * (t_cond_out_c - t_cond_in_c))
                # distribute new mass flow evenly to responders
                if len(result_mdot_tab_kg_per_s) > 0:
                    result_mdot_tab_kg_per_s = np.array(result_mdot_tab_kg_per_s) + (
                        mdot_cond_new - mdot_used_kg_per_s
                    ) / len(result_mdot_tab_kg_per_s)
                else:
                    result_mdot_tab_kg_per_s = np.array([mdot_cond_new])

        if mdot_cond_new is not None:
            pinch_c = self._get_element_param(prosumer, 'pinch_c')
            (q_cond_kw, p_comp_kw, q_evap_kw, cop_hp,
             mdot_cond_kg_per_s, t_cond_in_c, t_cond_out_c,
             mdot_evap_kg_per_s, t_evap_in_c, t_evap_out_c) = self._calculate_heat_pump(
                prosumer,
                mdot_cond_new,
                t_cond_out_required_c,
                t_cond_in_required_c,
                self._t_evap_in_c,
                pinch_c,
            )

        # --- Verdampferseite wärmegeführt "nachziehen" -----------------------------
        # q_evap_kw/t_evap_in_c sind an dieser Stelle das Ergebnis der kondensator-
        # getriebenen Berechnung ("erzeugte Kälte"). t_evap_out wird auf den von den
        # Evap-Respondern angeforderten Wert fixiert; mdot_evap wird daraus per
        # Energiebilanz bestimmt und per Merit-Order/Overflow-Strategy verteilt.
        # Reicht q_evap_kw nicht, wird mdot_evap entsprechend reduziert.
        result_mdot_evap_tab_kg_per_s = mdot_tab_evap_required_kg_per_s
        if mdot_evap_required_kg_per_s > 1e-8:
            cp_evap_kj_per_kgk = self.evap_fluid.get_heat_capacity(
                CELSIUS_TO_K + (t_evap_in_c + t_evap_out_required_c) / 2
            ) / 1000
            delta_t_evap_c = abs(t_evap_in_c - t_evap_out_required_c)
            mdot_evap_available_kg_per_s = (
                q_evap_kw / (cp_evap_kj_per_kgk * delta_t_evap_c) if delta_t_evap_c > 1e-8 else 0.0
            )

            result_mdot_evap_tab_kg_per_s = self._merit_order_mass_flow(
                prosumer,
                mdot_evap_available_kg_per_s,
                mdot_tab_evap_required_kg_per_s,
                overflow_strategy=overflow_strategy,
            )
            mdot_evap_kg_per_s = np.sum(result_mdot_evap_tab_kg_per_s)
            t_evap_out_c = t_evap_out_required_c


        cp_cond_kj_per_kgk = self.cond_fluid.get_heat_capacity(
            CELSIUS_TO_K + (t_cond_out_c + t_cond_in_c) / 2) / 1000
        self._check_fluid_mix_balance(prosumer,
                                      q_kw=q_cond_kw,
                                      mdot_kg_per_s=mdot_cond_kg_per_s,
                                      t_out_c=t_cond_out_c,
                                      t_in_c=t_cond_in_c,
                                      result_mdot_tab_kg_per_s=result_mdot_tab_kg_per_s,
                                      cp_fluid_kj_per_kgk=cp_cond_kj_per_kgk)

        # result_fluid_mix = []
        # for mdot_kg_per_s in result_mdot_tab_kg_per_s:
        #     result_fluid_mix.append({FluidMixMapping.TEMPERATURE_KEY: t_cond_out_c,
        #                              FluidMixMapping.MASS_FLOW_KEY: mdot_kg_per_s})
        result_fluid_mix = [
            {
                FluidMixMapping.TEMPERATURE_KEY: t_cond_out_c,
                FluidMixMapping.MASS_FLOW_KEY: mdot_cond_kg_per_s
            },
            {
                FluidMixMapping.TEMPERATURE_KEY: t_evap_out_c,
                FluidMixMapping.MASS_FLOW_KEY: mdot_evap_kg_per_s
            }
        ]

        result = np.array([[q_cond_kw, p_comp_kw, q_evap_kw, cop_hp,
                            mdot_cond_kg_per_s, t_cond_in_c, t_cond_out_c,
                            mdot_evap_kg_per_s, t_evap_in_c, t_evap_out_c]])

        self.last_result = {
            "q_cond_kw": q_cond_kw,
            "p_comp_kw": p_comp_kw,
            "q_evap_kw": q_evap_kw,
            "cop_hp": cop_hp,
            "mdot_cond_kg_per_s": mdot_cond_kg_per_s,
            "t_cond_in_c": t_cond_in_c,
            "t_cond_out_c": t_cond_out_c,
            "mdot_evap_kg_per_s": mdot_evap_kg_per_s,
            "t_evap_in_c": t_evap_in_c,
            "t_evap_out_c": t_evap_out_c,
        }

        assert cop_hp >= 0, f"Heat Pump {self.name} COP is negative ({cop_hp}) for timestep {self.time} in prosumer {prosumer.name}"
        assert mdot_evap_kg_per_s >= 0, f"Heat Pump {self.name} mdot_evap_kg_per_s is negative ({mdot_evap_kg_per_s}) for timestep {self.time} in prosumer {prosumer.name}"
        assert mdot_cond_kg_per_s >= 0, f"Heat Pump {self.name} mdot_cond_kg_per_s is negative ({mdot_cond_kg_per_s}) for timestep {self.time} in prosumer {prosumer.name}"
        assert p_comp_kw >= 0, f"Heat Pump {self.name} p_comp_kw is negative ({p_comp_kw}) for timestep {self.time} in prosumer {prosumer.name}"
        assert q_cond_kw >= 0, f"Heat Pump {self.name} q_cond_kw is negative ({q_cond_kw}) for timestep {self.time} in prosumer {prosumer.name}"
        assert q_evap_kw >= 0, f"Heat Pump {self.name} q_evap_kw is negative ({q_evap_kw}) for timestep {self.time} in prosumer {prosumer.name}"
        max_t_cond_out_c = self._get_element_param(prosumer, 'max_t_cond_out_c')
        if not np.isnan(max_t_cond_out_c):
            assert t_cond_out_c <= max_t_cond_out_c, f"Heat Pump {self.name} t_cond_out_c is higher than the maximum ({t_cond_out_c} > {max_t_cond_out_c}) for timestep {self.time} in prosumer {prosumer.name}"

        if np.isnan(self.t_keep_return_c) or mdot_evap_kg_per_s == 0 or abs(t_evap_out_c - self.t_keep_return_c) < TEMPERATURE_CONVERGENCE_THRESHOLD_C or len(self._get_mapped_initiators_on_same_level(prosumer)) == 0:
            # If the actual output temperature is the same as the promised one, the storage is correctly applied
            self.finalize(prosumer, result, result_fluid_mix)
            self.applied = True
            self.t_previous_evap_out_c = np.nan  # FIXME: should be nan ?
            self.t_previous_evap_in_c = np.nan
            self.mdot_previous_evap_kg_per_s = np.nan
            self.p_comp_previous_kw = p_comp_kw  # Store the last compressor power value
        else:
            # Else, reapply the upstream controllers with the new temperature so no energy appears or disappears
            self._unapply_initiators(prosumer)
            self.t_previous_evap_out_c = t_evap_out_c
            self.t_previous_evap_in_c = t_evap_in_c
            self.mdot_previous_evap_kg_per_s = mdot_evap_kg_per_s
            # self.p_comp_previous_kw = p_comp_kw
            self.input_mass_flow_with_temp = {FluidMixMapping.TEMPERATURE_KEY: np.nan,
                                              FluidMixMapping.MASS_FLOW_KEY: np.nan}