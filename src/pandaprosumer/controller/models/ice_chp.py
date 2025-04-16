import numpy as np
from pandaprosumer.controller.base import BasicProsumerController
import json
import pandas as pd
from pandaprosumer.library import lib_dir
import os
import sys
import logging  
logging.basicConfig(handlers=[logging.NullHandler()], force=True)              #prevents printing warnings to the console                                                             
logger = logging.getLogger("ice_chp_logger")


class IceChpController(BasicProsumerController):

    @classmethod
    def name(cls):
        return "ice_chp_control"        
    
    
    def __init__(
        self, 
        prosumer,
        chp_object,
        order=0,
        level=0,
        in_service=True,
        index=None,    
        **kwargs):
        """Initialise the attributes of the object

        Parameters
        ----------
        prosumer: prosumer container
        chp_object: chp component - Chp()
        data_source: object of type pandas.DataFrame ---> dataset in pandas format
        order: order of the chp object in the network (list) ---> default: 0 
        level:
        in_service: (bool) optional ---> default: True
        index: optional ---> default: None
        """
        super().__init__(
            prosumer,
            chp_object,
            order=order,
            level=level,
            in_service=in_service,
            index=index,
            **kwargs,
        )
                
        # Initialising variables that sum results of all time steps:
        self.acc_m_fuel_in_kg = 0
        self.acc_m_co2_equiv_kg = 0
        self.acc_m_co2_inst_kg = 0
        self.acc_m_nox_mg = 0
        self.acc_time_ice_chp_oper_s = 0
        self.applied = None
        
        
        # Open the file with CHP maps & read into memory the chosen map & read CHP static input data:
        _chp_file = f'{lib_dir}/chp_maps/ice_chp_maps.json'
        _fuel_file = f'{lib_dir}/chp_maps/fuel_maps.json'
        #
        size_kw = self._get_element_param(prosumer, "size")
        ice_chp_json_data = self.read_json_maps(_chp_file)
        self.ice_chp_map = self.select_chp_map(size_kw, ice_chp_json_data)
        #
        self.fuel_type = self._get_element_param(prosumer, "fuel")
        self.fuel_data = self.read_json_maps(_fuel_file)
        #
        self.h_ice_chp_m = self._get_element_param(prosumer, "altitude")
        #---------------------------------------------------------------
        
        
    # Defining the variable that represents the energy demand:
    def q_requested_kw(self, prosumer):
        """
        Calculates the heat to deliver in kW.

        :param prosumer: The prosumer object
        :return: Heat to deliver in kW
        """
        q_requested_kw = 0.
        for responder in self._get_generic_mapped_responders(prosumer):
            q_requested_kw += responder.q_to_receive_kw(prosumer)
        return q_requested_kw


    def time_step(self, prosumer, time):
        """It is the first call in each time step, thus suited for things like
        reading profiles or prepare the controller for the next control step.
        
        .. note:: This method is ONLY being called during time-series simulations!

        :param prosumer: 
        :param time: 
        """
        super().time_step(prosumer, time)
        self.step_results = np.full([len(self.element_index), len(self.obj.result_columns)], np.nan)
        self.time = time
        self.applied = False


    def is_converged(self, container):
        """This method is calculated whether or not the controller converged. This is
        where any target values are being calculated and compared to the actual
        measurements. Returns convergence of the controller.

        :param container: _description_
        :type container: _type_
        """
        return self.applied


    def control_step(self, prosumer):
        #       
        # ICE CHP CALCULATIONS:
        # =====================
        # New CHP instance:
        # 1 - Read time step input data:
        cycle_type = self._get_input("cycle")
        t_ice_chp_k = self._get_input("t_intake_k")
        #
        q_requested_kw = self.q_requested_kw(prosumer)

        #
        # 2 - Calculations:
        # 2a - Calculate CHP outputs:
        loadList = self.calculate_load(cycle_type, q_requested_kw, t_ice_chp_k, self.h_ice_chp_m, self.ice_chp_map, self.time)
        load = loadList[1]
        p_el_out_kw = self.calculate_electrical_power_out(load, self.ice_chp_map)
        p_th_out_kw = self.calculate_recovered_heat_flow(load, self.ice_chp_map)
        p_in_kw = self.calculate_input_energy_flow(load, self.ice_chp_map)
        p_rad_out_kw = self.calculate_radiation(load, self.ice_chp_map)
        mdot_fuel_in_kg_per_s = self.calculate_fuel_input_mass_flow(p_in_kw, self.fuel_type, self.fuel_data)
        m_fuel_in_kg = mdot_fuel_in_kg_per_s * self.resol                
        self.acc_m_fuel_in_kg += m_fuel_in_kg
        #
        # cumulative fuel consumption
        #
        # 2b - Calculate emissions:
        m_co2_equiv_kg = self.calculate_co2_equiv_mass_flow(p_in_kw, self.fuel_type, self.fuel_data) * self.resol
        m_co2_inst_kg = self.calculate_co2_instant_mass_flow(mdot_fuel_in_kg_per_s, self.fuel_type, self.fuel_data) * self.resol
        m_nox_mg = self.calculate_nox_mass_flow(load, self.ice_chp_map) * self.resol
        # Calculate cumulative emissions
        self.acc_m_co2_equiv_kg += m_co2_equiv_kg
        self.acc_m_co2_inst_kg += m_co2_inst_kg
        self.acc_m_nox_mg += m_nox_mg
        #
        # 3 - Determine the operational time of the ICE CHP
        if load == 0:
            time_ice_chp_oper_s = 0
        else:
            time_ice_chp_oper_s = self.resol
        #        
        self.acc_time_ice_chp_oper_s += time_ice_chp_oper_s
        # 
        # 4 - Calculate the total efficiency:
        p_loss_kw = self.calculate_energy_flow_loss(p_in_kw, p_th_out_kw, p_el_out_kw)
        ice_chp_efficiency = self.calculate_efficiency(p_in_kw, p_loss_kw)
        #
        # 5 - Results array:
        result = np.array([
                  pd.Series(load),
                  pd.Series(p_in_kw),
                  pd.Series(p_el_out_kw),
                  pd.Series(p_th_out_kw),
                  pd.Series(p_rad_out_kw),
                  pd.Series(ice_chp_efficiency),
                  pd.Series(mdot_fuel_in_kg_per_s),
                  pd.Series(self.acc_m_fuel_in_kg),
                  pd.Series(self.acc_m_co2_equiv_kg),
                  pd.Series(self.acc_m_co2_inst_kg),
                  pd.Series(self.acc_m_nox_mg),
                  pd.Series(self.acc_time_ice_chp_oper_s)])

        self.finalize(prosumer, result.T)

        self.applied = True
        #------------ end of ICE CHP calculations -----------------------------
        

    # ICE CHP FUNCTIONS:
    # ==================
    def read_json_maps(self, map_filename:str) -> dict:
        """
        Opens a JSON file and reads data from it.

            :param map_filename: name of the file with maps to import
            :return jason_data: contains all data in the JSON file
            """
        with open(map_filename, 'r') as jfile:
            json_data = json.load(jfile)
        #
        return json_data
 
    
    def select_chp_map(self, size_kw:int, json_data:dict) -> dict:
        """
        Selects a ICE CHP map from CHP JSON data.

            :param size_kw: nominal CHP size (output: electrical power) in kW
            :param json_data: all data in a JSON file 
            :return chp_map_data: contains data of the chosen CHP from the JSON file
            """
        # Check if the chosen nominal size of the CHP exists:
        ice_chp_sizes_nominal = json_data['chp_ice_size_kw']
        #Check if the size is greater than the maximum value in the map:
        size_nominal_max_kw = max(ice_chp_sizes_nominal)
        if size_kw > size_nominal_max_kw:
            sys.exit(f"The size of the chosen ICE CHP is too large. The largest available ICE CHP size is {size_nominal_max_kw} kW. Choose a smaller size or add a new CHP map. \nTerminating the program...\n")
        else: 
            # Check if the size is in the map:
            if size_kw in ice_chp_sizes_nominal:
                size_index = ice_chp_sizes_nominal.index(size_kw)
                chp_map_data = json_data["chp_ice_map"][size_index]                    # Selects only the map of the chosen CHP size
                #       
                return chp_map_data
            # If the size is not in the map, choose the next highest & print a warning:
            else:
                index = 0
                while size_kw > ice_chp_sizes_nominal[index]:
                    index += 1 
                #
                chp_map_data = json_data["chp_ice_map"][index]
                #
                logger.warning(f"The chosen ICE CHP size ({size_kw} kW) is not in the list. The next bigger size ({ice_chp_sizes_nominal[index]} kW) will be used.\n")
                #
                return chp_map_data
   
        
    def calculate_air_density(self, temperature_k:float, altitude_m:float, pressure_ref_pa=101325, m_molar_air_kg_per_mol=0.0289652, g_m_per_s2=9.81, gas_const_universal_j_per_molk=8.314) -> float:
        """
        Calculates air density according to the ideal gas law.

            :param temperature_k: air temperature in K
            :param altitude_m: the altitude of the CHP location in m
            :param pressure_ref_pa: reference pressure in Pa
            :param m_molar_air_kg_per_mol: air molar mass in kg/mol 
            :param g_m_per_s2: gravitational acceleration in m/s2
            :param gas_const_universal_j_per_molk: universal gas constant in J/molK
            :return density: air density in kg/m3
            """
        # (i) Barometric formula: air pressure as a function of temperature and altitude:
        a = (- m_molar_air_kg_per_mol * g_m_per_s2 * altitude_m) / (gas_const_universal_j_per_molk * temperature_k)
        pressure_calc_pa = pressure_ref_pa * np.exp(a)
        #
        # (ii) Density as a function of temperature and altitude:
        density_kg_per_m3 = (pressure_calc_pa * m_molar_air_kg_per_mol) / (gas_const_universal_j_per_molk * temperature_k)   
        #
        return density_kg_per_m3


    def calculate_density_ratio(self, temperature_act_k:float, altitude_act_m:float, map_chp:dict) -> float:    
        """
        Calculates the ratio between the reference density for which the CHP maps were designed and the actual density of the air at intake.

            :param temperature_act_k: actual air temperature at CHP intake in K
            :param altitude_act_m: the actual altitude of the CHP location in m
            :param map_engine: data for the chosen CHP size
            :return ratio: ratio between map reference density and actual density
            """
        # Get reference values from the CHP map:
        temperature_ref_k = map_chp['temperature_reference_k']
        altitude_ref_m = map_chp['altitude_reference_m']
        p_ref_pa = map_chp['pressure_reference_pa']
        m_molar_air_kg_per_mol = map_chp['air_molar_mass_kg_per_mol']
        g_m_per_s2 = map_chp['gravitational_acc_m_per_s2']
        r_universal_j_per_molk = map_chp['universal_gas_const_j_per_molk']
        #
        # Reference density ---> corresponds to data in the CHP maps:
        density_ref = self.calculate_air_density(temperature_ref_k, altitude_ref_m, p_ref_pa, m_molar_air_kg_per_mol, g_m_per_s2, r_universal_j_per_molk)
        #
        # Actual density of the modelled CHP:
        density_act = self.calculate_air_density(temperature_act_k, altitude_act_m, p_ref_pa, m_molar_air_kg_per_mol, g_m_per_s2, r_universal_j_per_molk)
        #
        # Ratio:
        ratio = density_act / density_ref
        #
        if ratio > 1.00:
            ratio = 1.00
        #
        return ratio


    def calculate_load(self, cycle:int, demand_kw:float, temperature_k:float, altitude_m:float, map_chp:dict, time) -> float: 
        """
        Calculates the engine load based on the desired output.

            :param cycle: defines output priority (electrical power = 1, heat = 2) 
            :param demand_kw: current demand value in kW 
            :param temperature_k: current air temperature at intake in K
            :param altitude_m: the altitude of the CHP location in m
            :param map_chp: data for the chosen CHP size
            :param time: the current step's simulation time
            :returns:
                - load - CHP load under reference conditions in %
                - load_actual - CHP load under actual conditions in %
            """   
        map_load = map_chp['engine_load_percent']
        map_load_limits = map_chp['load_limits_percent']
        map_p_el = map_chp['power_el_kw']
        map_p_th_recovered = map_chp['heat_flow_recovered_kw']
        #
        load = 0
        #
        # Check if the value of the specified output type is in the map:
        # If desired output: ELECTRICITY
        if cycle == 1:
            # Check if the value of the desired output is within the range of the chosen CHP:
            if demand_kw > max(map_p_el):
                logger.warning(f"[Event at {time}]: The demand ({demand_kw} kW) is greater than the maximum output of the chosen CHP ({max(map_p_el)} kW). The maximum CHP output will be used.\n")
                load = map_load_limits[1]
            else:
                if demand_kw in map_p_el:
                    # If the desired electrical demand is a map value
                    _position = map_p_el.index(demand_kw)
                    load = map_load[_position]
                else:
                    # If the desired electrical demand is not a map value ---> interpolate
                    load = np.interp(demand_kw, map_p_el[::-1], map_load[::-1])    
                    #
        # If desired output: HEAT
        elif cycle == 2:
            # Check if the value of the desired output is within the range of the chosen CHP:
            if demand_kw > max(map_p_th_recovered):
                logger.warning(f"[Event at {time}]: The demand ({demand_kw} kW) is greater than the maximum output the chosen CHP can generate ({max(map_p_th_recovered)} kW). The maximum CHP output will be used.\n")
                load = map_load_limits[1]
            else:
                if demand_kw in map_p_th_recovered:
                    # If the desired thermal demand is a map value
                    _position = map_p_th_recovered.index(demand_kw)
                    load = map_load[_position]
                else:
                    # If the desired thermal demand is not a map value ---> interpolate
                    load = np.interp(demand_kw, map_p_th_recovered[::-1], map_load[::-1])    
                    #
        # Calculate the ratio and perceived load:
        ratio = self.calculate_density_ratio(temperature_k, altitude_m, map_chp)
        load_actual = load * ratio 
        #
        # Run a limit check:
        if load_actual < map_load_limits[0] and load > 0:                  
            logger.warning(f"[Event at {time}]: The current engine load ({load}%) is below the allowed lower limit ({map_load_limits[0]}%). The load will drop to 0%.\n")
            load_actual = 0
        elif load_actual > map_load_limits[1]:
            logger.warning(f"[Event at {time}]: The current engine load ({load}%) is greater than the allowed upper limit ({map_load_limits[1]}%). The load will drop to the maximum limit.\n")
            load_actual = map_load_limits[1]    
        #
        return load, load_actual


    ### 2. CHP INPUTS:
    def calculate_input_energy_flow(self, load:float, map_chp:dict) -> float:
        """
        Determines the input energy flow into the engine.

            :param load_calc: CHP load in % 
            :param map_engine: data for the chosen CHP size
            :return p_in_kw: required energy flow for the defined load/output power in kW
            """
        map_load = map_chp['engine_load_percent']
        map_p_in = map_chp['energy_flow_input_kw']
        #
        if load in map_load:
            # If the calculated CHP load is a map value
            _position = map_load.index(load)
            p_in_kw = map_p_in[_position]
        else:
            # If the calculated CHP load is not a map value ---> interpolate
            p_in_kw = np.interp(load, map_load[::-1], map_p_in[::-1])    
        #
        return p_in_kw


    def calculate_fuel_input_mass_flow(self, p_in_kw:float, fuel_type:str, map_fuel:dict) -> float:
        """
        Determines the required fuel mass flow.

            :param p_in_kw: required energy flow into the CHP in kW
            :param fuel_type: selected fuel type (options: ng, sng1, sng2, sng3, sng4, sng5, sng6)
            :param map_fuel: data for the fuels in the fuels JSON file
            :return mdot_fuel_in_kg_per_s: required fuel mass flow in kg/s 
            """
        fuel_names = map_fuel['fuel_types']
        _position = fuel_names.index(fuel_type)
        #
        lhv_values = map_fuel['lower_heating_value_kwh_per_kg']
        lhv_kwh_per_kg = lhv_values[_position]
        #
        mdot_fuel_in_kg_per_s = (p_in_kw / lhv_kwh_per_kg) * (1/3600)
        #
        return mdot_fuel_in_kg_per_s


    ### 3. CHP OUTPUTS:
    def calculate_electrical_power_out(self, load:float, map_chp:dict) -> float:
        """
        Calculates the generated electrical power.

            :param load: CHP load in %
            :param map_chp: data for the chosen CHP size from the map in the JSON file
            :return p_el_out_kw: output electrical power on the generator in kW
            """    
        map_load = map_chp['engine_load_percent']
        map_p_el_out = map_chp['power_el_kw']
        #
        if load in map_load:
            # If the calculated CHP load is a map value
            _position = map_load.index(load)    
            p_el_out_kw = map_p_el_out[_position]  
        else:
            # If the calculated CHP load is not a map value ---> interpolate
            p_el_out_kw = np.interp(load, map_load[::-1], map_p_el_out[::-1])    
        #
        return p_el_out_kw


    def calculate_recovered_heat_flow(self, load:float, map_chp:dict) -> float:
        """
        Calculates the recovered energy (heat) flow.

            :param load: CHP load in %
            :param map_chp: data for the chosen CHP size from the map in the JSON file
            :return p_th_out_kw: useful heat flow extracted from the ICE CHP in kW
            """    
        map_load = map_chp['engine_load_percent']
        map_p_th_out = map_chp['heat_flow_recovered_kw']
        #
        if load in map_load:
            # If the calculated engine load is a map value
            _position = map_load.index(load)    
            p_th_out_kw = map_p_th_out[_position]  
        else:
            # If the calculated engine load is not a map value ---> interpolate
            p_th_out_kw = np.interp(load, map_load[::-1], map_p_th_out[::-1])    
        #
        return p_th_out_kw


    def calculate_radiation(self, load:float, map_chp:dict) -> float:
        """
        Determines the amount of radiation from the ICE CHP unit into the sorounding space. 
        
            :param load: CHP load in %
            :param map_chp: data for the chosen CHP size from the map in the JSON file
            :return p_rad_out_kw: radiation int in kW
            """
        map_load = map_chp['engine_load_percent']
        map_p_rad = map_chp['heat_flow_radiation_kw']
        #
        if load in map_load:
            # If the calculated engine load is a map value
            _position = map_load.index(load)    
            p_rad_out_kw = map_p_rad[_position]  
        else:
            # If the calculated engine load is not a map value ---> interpolate
            p_rad_out_kw = np.interp(load, map_load[::-1], map_p_rad[::-1])    
        #
        return p_rad_out_kw     


    def calculate_energy_flow_loss(self, p_in_kw:float, p_out_kw:float, p_el_kw:float) -> float:
        """
        Calculates the amount of energy flow that is lost ---> wasted heat.

            :param p_in_kw: input energy flow in kW
            :param p_out_kw: total recovered energy flow on the output side in kW
            :param p_el_kw: generated electrical power in kW
            :return p_loss_kw: wasted heat flow from the ICE CHP in kW
            """    
        p_loss_kw = p_in_kw - (p_out_kw + p_el_kw)
        #
        return p_loss_kw


    def calculate_efficiency(self, p_in_kw:float, p_loss_kw:float) -> float:
        """
        Calculates the efficiency of the entire ICE CHP.

            :param p_in_kw: input energy flow in kW
            :param p_loss_kw: lost energy flow in kW
            :return efficiency: efficiency of the ICE CHP in %
            """
        if p_in_kw == 0:
            efficiency = 0
        else:
            efficiency = ((p_in_kw - p_loss_kw) / p_in_kw) * 100
        #
        return efficiency


    def calculate_co2_instant_mass_flow(self, mdot_fuel_kg_per_s:float, fuel_type:str, map_fuel:dict) -> float:
        """
        Calculates CO2 emissions at the location of the ICE CHP (instantaneous emissions).

            :param mdot_fuel_kg_per_s: fuel mass flow in kg/s
            :param r_oxidised_c: fraction of fully oxidised carbon
            :param fuel_type: selected fuel type (options: ng, sng1, sng2, sng3, sng4, sng5, sng6) 
            :param map_fuel: data for the chosen CHP size from the map in the JSON file 
            :return mdot_co2_inst_kg_per_s: mass flow of CO2 emissions at the location of the ICE CHP in kg/s
            """
        _mass_molar_c_kg_per_mol = 0.012
        _mass_molar_co2_kg_per_mol = 0.044
        #
        # Get data from the fuel map ---> carbon fraction: 
        fuel_names = map_fuel['fuel_types']
        _position = fuel_names.index(fuel_type)
        r_total_c_all = map_fuel['carbon_fraction']                                #fraction of carbon in the chemical composition of the fuel [/]
        r_total_c = r_total_c_all[_position]
        #
        mdot_co2_inst_kg_per_s = mdot_fuel_kg_per_s * r_total_c * (_mass_molar_co2_kg_per_mol/_mass_molar_c_kg_per_mol)
        #
        return mdot_co2_inst_kg_per_s


    def calculate_co2_equiv_mass_flow(self, p_in_kw:float, fuel_type:str, map_fuel:dict) -> float:
        """
        Calculates equivalent CO2 emissions.

            :param p_in_kw: input energy flow in kW
            :param fuel_type: selected fuel type (options: ng, sng1, sng2, sng3, sng4, sng5, sng6) 
            :param map_fuel: data for the chosen CHP size from the map in the JSON file 
            :return mdot_co2_inst_kg_per_s: mass flow of CO2 emissions at the location of the ICE CHP in kg/s
            """
        fuel_names = map_fuel['fuel_types']
        _position = fuel_names.index(fuel_type)
        co2all = map_fuel['co2eq_kg_per_kwh']                                
        co2_eq_kg_per_kwh = co2all[_position]
        #
        mdot_co2_equiv_kg_per_s = p_in_kw * co2_eq_kg_per_kwh * (1 / 3600)
        #
        return mdot_co2_equiv_kg_per_s


    def calculate_nox_mass_flow(self, load:float, map_chp:dict) -> float:
        """
        Determines the amount of NOx emissions.

            :param load: CHP load in %
            :param map_chp: data for the chosen CHP size from the map in the JSON file
            :return mdot_nox_mg_per_s: mass flow of NOx emissions at the location of the ICE CHP in mg/s
            """
        map_load = map_chp['engine_load_percent']
        map_exhaust = map_chp['exhaust_flow_rate_m3n_per_h']
        dm_nox_mg_per_m3n = map_chp['emiss_rate_nox_mg_per_m3n']
        #
        if load in map_load:
            # If the calculated engine load is a map value
            _position = map_load.index(load)    
            vdot_exhaust_m3n_per_h = map_exhaust[_position]
        else:
            # If the calculated engine load is not a map value ---> interpolate
            vdot_exhaust_m3n_per_h = np.interp(load, map_load[::-1], map_exhaust[::-1])    
        #
        mdot_nox_mg_per_s = dm_nox_mg_per_m3n * vdot_exhaust_m3n_per_h * (1 / 3600)
        #
        return mdot_nox_mg_per_s
    
    #=============================== END OF ICE CHP ===================================
    
        