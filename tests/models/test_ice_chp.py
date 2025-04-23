import pytest
from pandaprosumer.create import *
from pandaprosumer.create_controlled import *


"""
TESTS:

1. Creation of an ICE CHP element  

2. Creation of an ICE CHP element with custom parameter values 

3. Creation of an ICE CHP controller 

4. Test the input and result columns of an ICE CHP controller 

5. Getting input values ---> static input

6. Getting controller data ---> dynamic input

7. Run the controller without a demand

8. Run the controller with a single demand

9. Test the ICE CHP size selection

10. Test ICE CHP interpolation

11. Test ICE CHP load limits

12. Test the fuel input type 

13. Test the cycle

"""

# parameter values (static input)
def _default_arguments():
    return {'size': 350,
            'fuel': 'ng', 
            'altitude': 0,
            'name': 'example_ice_chp'
            }

# definition of the time period
def _default_period(prosumer):
    time_step_s = 900          # duration of a single time step in seconds
    return create_period(prosumer, 
                         time_step_s,
                         name="foo",
                         start="2020-01-01 00:00:00",
                         end="2020-01-01 11:59:59",
                         timezone="utc")


class TestIceChp:
    """
    Tests the basic functionalities of an ICE CHP element and controller
    """
    
#========================| STANDARD TESTS |====================================
    # TEST 1
    def test_define_element(self):    
        """
        Test the creation of an ICE CHP element with default parameters values
        """
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)
        create_ice_chp(prosumer, 350.0, "ng")    

        assert hasattr(prosumer, "ice_chp")
        assert len(prosumer.ice_chp) == 1

        expected_columns = ["size", "fuel", "altitude", "in_service", "name"]
        expected_values = [350.0, "ng", 0.0, True, None]
        
        assert list(prosumer.ice_chp.columns) == expected_columns
        assert list(prosumer.ice_chp.iloc[0]) == expected_values

    
    # TEST 2
    def test_define_element_with_parameters(self):    
        """
        Test the creation of an ICE CHP element with custom parameters values
        """
        prosumer = create_empty_prosumer_container()
        create_period(prosumer, 1)
        ice_chp_idx = create_ice_chp(prosumer, 350.0, "ng", 0.0, True, "example_ice_chp")

        assert hasattr(prosumer, 'ice_chp')
        assert len(prosumer.ice_chp) == 1
        assert prosumer.ice_chp.index[0] == ice_chp_idx
        
        # Checks names of columns (all string!):
        assert isinstance(prosumer.ice_chp.columns[0], str)       # size 
        assert isinstance(prosumer.ice_chp.columns[1], str)       # fuel type
        assert isinstance(prosumer.ice_chp.columns[2], str)       # altitude  
        assert isinstance(prosumer.ice_chp.columns[3], str)       # in_service 
        assert isinstance(prosumer.ice_chp.columns[4], str)       # name
        # Checks input types:
        assert isinstance(prosumer.ice_chp.iloc[0].values[0], float)     # size
        assert isinstance(prosumer.ice_chp.iloc[0].values[1], str)       # fuel type
        assert isinstance(prosumer.ice_chp.iloc[0].values[2], float)     # altitude
        assert bool(prosumer.ice_chp.iloc[0].values[3])                  # in_service 
        assert isinstance(prosumer.ice_chp.iloc[0].values[4], str)       # name
        
        
    # TEST 3    
    def test_define_controller(self):      # OK WITH THE -s ARGUMENT WHEN RUNNING THE TEST (FOR THE PROMPT)
        """
        Test the creation of an ICE CHP controller in a prosumer container
        """
        prosumer = create_empty_prosumer_container()
        create_controlled_ice_chp(prosumer, index=None, in_service=True, level=0, order=0, period=_default_period(prosumer), **_default_arguments())

        assert hasattr(prosumer, "controller")
        assert len(prosumer.controller) == 1 
        
    
    # TEST 4
    def test_controller_columns_default(self):      
        """
        Test the input and result columns of an ICE CHP controller
        """
        prosumer = create_empty_prosumer_container()

        ice_chp_controller_idx = create_controlled_ice_chp(prosumer, index=None, in_service=True, level=0, order=0, period=_default_period(prosumer), **_default_arguments())
        ice_chp_controller = prosumer.controller.iloc[ice_chp_controller_idx].object

        input_columns_expected = ['cycle', 't_intake_k']
        result_columns_expected = ['load', 'p_in_kw', 'p_el_out_kw', 'p_th_out_kw', 'p_rad_out_kw', 'ice_chp_efficiency', 'mdot_fuel_in_kg_per_s', 'acc_m_fuel_in_kg', 'acc_co2_equiv_kg', 'acc_co2_inst_kg', 'acc_nox_mg', 'acc_time_ice_chp_oper_s']

        assert ice_chp_controller.input_columns == input_columns_expected
        assert ice_chp_controller.result_columns == result_columns_expected
     
      
    # TEST 5     
    def test_controller_get_input(self):     
        """
        Test the method to get the input values of an ICE CHP controller
    
        """
        prosumer = create_empty_prosumer_container()

        params = {'size': 350,
                  'fuel': 'ng',
                  'altitude': 0,
                  'name': 'example_ice_chp'}
        
        ice_chp_controller_idx = create_controlled_ice_chp(prosumer, order=0, period=_default_period(prosumer), **params)
    
        ice_chp_controller = prosumer.controller.iloc[ice_chp_controller_idx].object
    
        assert np.isnan(ice_chp_controller._get_input('cycle'))
        
        ice_chp_controller.inputs = np.array([[1, 297]])
        assert ice_chp_controller._get_input('cycle', prosumer) == pytest.approx(1)
    
        with pytest.raises(KeyError):
            ice_chp_controller._get_input('size', prosumer)
        
        
    # TEST 6
    def test_controller_get_param(self):      
        """
        Test the method to get the input values of an ICE CHP controller
        """
        prosumer = create_empty_prosumer_container()
        ice_chp_controller_idx = create_controlled_ice_chp(prosumer, order=0, period=_default_period(prosumer), **_default_arguments())
        ice_chp_controller = prosumer.controller.iloc[ice_chp_controller_idx].object

        assert ice_chp_controller._get_element_param(prosumer, 'size') == pytest.approx(350.) 
        assert ice_chp_controller._get_element_param(prosumer, 'fuel') == 'ng'        
        assert ice_chp_controller._get_element_param(prosumer, 'p_in_kw') is None
        #assert ice_chp_controller._get_element_param(prosumer, 'p_in_kw') == pytest.approx(0.0)  # this shouldn't pass
            
          
    # TEST 7
    def test_controller_run_control_no_demand(self):    
        """
        Test the ICE CHP controller without any demand
        Expect the ICE CHP to be off
        """
        prosumer = create_empty_prosumer_container()
        ice_chp_controller_idx = create_controlled_ice_chp(prosumer, order=0, period=_default_period(prosumer), **_default_arguments())
        ice_chp_controller = prosumer.controller.iloc[ice_chp_controller_idx].object
        
        # time series input:
        # 'cycle', 't_intake_k'
        ice_chp_controller.inputs = np.array([[1, 293.15]])  # dynamic input (data_model/ice_chp.py) ---> for 1 time step
        ice_chp_controller.time_step(prosumer, "2020-01-01 00:00:00")

        ice_chp_controller.control_step(prosumer)

        # output:
        # 'load', 'p_in_kw', 'p_el_out_kw', 'p_th_out_kw', 'p_rad_out_kw', 'ice_chp_efficiency', 'mdot_fuel_in_kg_per_s', 'acc_m_fuel_in_kg', 'acc_co2_equiv_kg', 'acc_co2_inst_kg', 'acc_nox_mg', 'acc_time_ice_chp_oper_s'        
        expected = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0] # results ---> dynamic output for 1 time step

        assert ice_chp_controller.step_results == pytest.approx(np.array([expected]))
        
        
    # TEST 8
    def test_controller_run_control_demand(self):    
        """
        Test the ICE CHP controller with a demand
        """
        prosumer = create_empty_prosumer_container()
        ice_chp_controller_idx = create_controlled_ice_chp(prosumer, order=0, period=_default_period(prosumer), **_default_arguments())
        ice_chp_controller = prosumer.controller.iloc[ice_chp_controller_idx].object
        
        # time series input:
        # 'cycle', 't_intake_k'
        ice_chp_controller.inputs = np.array([[1, 293.15]])  # dynamic input (data_model/ice_chp.py) ---> for 1 time step
        # demand:
        ice_chp_controller.q_requested_kw = lambda x: 1000

        ice_chp_controller.time_step(prosumer, "2020-01-01 00:00:00")
        ice_chp_controller.control_step(prosumer)

        # output:
        #    0        1           2              3              4                   5                    6                         7                  8                 9                10                11              
        # 'load', 'p_in_kw', 'p_el_out_kw', 'p_th_out_kw', 'p_rad_out_kw', 'ice_chp_efficiency', 'mdot_fuel_in_kg_per_s', 'acc_m_fuel_in_kg', 'acc_co2_equiv_kg', 'acc_co2_inst_kg', 'acc_nox_mg', 'acc_time_ice_chp_oper_s'        
        #            0     1      2       3      4        5             6            7        8         9         10     11    
        expected = [100, 875.0, 350.0, 305.78, 54.64, 74.946286, 0.0171165884, 15.40492956, 50.75, 44.05809852, 193725, 900.0] # results ---> dynamic output for 1 time step

        assert ice_chp_controller.step_results == pytest.approx(np.array([expected]), rel=1e-6)
        
        
#======================| ICE CHP SPECIFIC TESTS |==============================

    # TEST 9
    def test_ice_chp_size_selection(self):   
        """
        Test the ICE CHP size selection for sizes not in list
        """
        prosumer = create_empty_prosumer_container()
        
        params = {'size': 500,     # this CHP size not in the list ---> should give results for 700 kW
                  'fuel': 'ng',
                  'altitude': 0,
                  'name': 'new_ice_chp'} 

        ice_chp_controller_idx = create_controlled_ice_chp(prosumer, order=0, period=_default_period(prosumer), **params)
        ice_chp_controller = prosumer.controller.iloc[ice_chp_controller_idx].object
            
        # time series input:
        # 'cycle', 't_intake_k'
        ice_chp_controller.inputs = np.array([[1, 293.15]])  # dynamic input (data_model/ice_chp.py) ---> for 1 time step
        # demand:
        ice_chp_controller.q_requested_kw = lambda x: 1000

        ice_chp_controller.time_step(prosumer, "2020-01-01 00:00:00")
        ice_chp_controller.control_step(prosumer)

        expected_p_in = 1750.00

        assert ice_chp_controller.step_results[0,1] == pytest.approx(np.array(expected_p_in), rel=1e-4)    
    
    
    # TEST 10
    def test_controller_interpolation(self):     
        """
        Test the ICE CHP interpolation
        """
        test_level_percent = 80
        
        params = {'fuel': 'ng',
                  'altitude': 0,
                  'name': 'new_ice_chp'} 
        
        size_val = 350
        
        demand = size_val * test_level_percent / 100
        
        prosumer = create_empty_prosumer_container()
        ice_chp_controller_idx = create_controlled_ice_chp(prosumer, order=0, period=_default_period(prosumer), size=size_val, **params)
        ice_chp_controller = prosumer.controller.iloc[ice_chp_controller_idx].object
            
        # time series input:
        # 'cycle', 't_intake_k'
        ice_chp_controller.inputs = np.array([[1, 293.15]])  # dynamic input (data_model/ice_chp.py) ---> for 1 time step
        # demand
        ice_chp_controller.q_requested_kw = lambda x: demand

        ice_chp_controller.time_step(prosumer, "2020-01-01 00:00:00")
        ice_chp_controller.control_step(prosumer)

        expected_p_el = 280.008
        
        assert ice_chp_controller.step_results[0,2] == pytest.approx(np.array(expected_p_el), rel=1e-3)

    
    # TEST 11
    def test_controller_lower_limit(self):     
        """
        Test the ICE CHP limits for the load - lower limit = 20%
        """
        test_level_percent = 10
        
        params = {'fuel': 'ng',
                  'altitude': 0,
                  'name': 'new_ice_chp'} 
        
        size_val = 350
        
        demand = size_val * test_level_percent / 100
        
        prosumer = create_empty_prosumer_container()
        ice_chp_controller_idx = create_controlled_ice_chp(prosumer, order=0, period=_default_period(prosumer), size=size_val, **params)
        ice_chp_controller = prosumer.controller.iloc[ice_chp_controller_idx].object
            
        # time series input:
        # 'cycle', 't_intake_k'
        ice_chp_controller.inputs = np.array([[1, 293.15]])  # dynamic input (data_model/ice_chp.py) ---> for 1 time step
        # demand
        ice_chp_controller.q_requested_kw = lambda x: demand

        ice_chp_controller.time_step(prosumer, "2020-01-01 00:00:00")
        ice_chp_controller.control_step(prosumer)

        expected_p_el = 0        
        expected_load = 0
        
        assert ice_chp_controller.step_results[0,4] == pytest.approx(np.array(expected_p_el), rel=1e-4)
        assert ice_chp_controller.step_results[0,0] == pytest.approx(np.array(expected_load), rel=1e-4)
        
    
    # TEST 12:
    def test_ice_chp_input_type(self):    
        """
        Checks the correct input for the ICE CHP parameters - version 2
        """
        prosumer = create_empty_prosumer_container()

        params = {'size': 350, 
                  'altitude': 0,
                  'name': 'example_ice_chp'} 
        
        fuel_val = 10
        
        ice_chp_controller_idx = create_controlled_ice_chp(prosumer, order=0, period=_default_period(prosumer), fuel=fuel_val, **params)
        ice_chp_controller = prosumer.controller.iloc[ice_chp_controller_idx].object
        
        stored_fuel = ice_chp_controller._get_element_param(prosumer, "fuel")
        
        assert not isinstance(stored_fuel, str) 

  
    # TEST 13
    def test_ice_chp_cycle(self):
        """
        Test the ICE CHP cycle (switching between topping and bottoming) in the input 
        """
        prosumer = create_empty_prosumer_container()

        ice_chp_controller_idx = create_controlled_ice_chp(
            prosumer, order=0, period=_default_period(prosumer), **_default_arguments())
        ice_chp_controller = prosumer.controller.iloc[ice_chp_controller_idx].object
            
        cycle_test = 2         # output preference: heat (for electricity, use value: 1)

        # dynamic input:                                                        
        # 'cycle', 't_intake_k'
        ice_chp_controller.inputs = np.array([[cycle_test, 293.15]])  # dynamic input (data_model/ice_chp.py) ---> for 1 time step
        ice_chp_controller.q_requested_kw = lambda x: 1000

        ice_chp_controller.time_step(prosumer, "2020-01-01 00:00:00")
        ice_chp_controller.control_step(prosumer)

        expected_p_th_out_1 = 350.00
        expected_p_th_out_2 = 305.78

        if cycle_test == 1:
            assert ice_chp_controller.step_results[0,3] == pytest.approx(np.array(expected_p_th_out_1))
        elif cycle_test == 2:
            assert ice_chp_controller.step_results[0,3] == pytest.approx(np.array(expected_p_th_out_2))
            
