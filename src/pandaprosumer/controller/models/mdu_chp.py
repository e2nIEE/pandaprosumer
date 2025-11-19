import os
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import joblib

from pandaprosumer.controller.mapped import MappedController
from pandaprosumer.mapping import FluidMixMapping


# LSTM Model Definition
class Attention(nn.Module):
    """Attention mechanism for LSTM model"""

    def __init__(self, hidden_size):
        super(Attention, self).__init__()
        self.attention = nn.Linear(hidden_size, hidden_size)
        self.context_vector = nn.Linear(hidden_size, 1, bias=False)

    def forward(self, lstm_output):
        attn_weights = self.context_vector(torch.tanh(self.attention(lstm_output)))
        attn_weights = torch.softmax(attn_weights, dim=1)
        weighted_output = torch.sum(lstm_output * attn_weights, dim=1)
        return weighted_output


class BiLSTMAttnRegressor(nn.Module):
    """Bidirectional LSTM with attention for CHP parameter prediction"""

    def __init__(self, input_size, hidden_size, output_size, num_layers, dropout):
        super(BiLSTMAttnRegressor, self).__init__()
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.lstm = nn.LSTM(input_size, hidden_size, num_layers,
                            batch_first=True, dropout=dropout, bidirectional=True)
        self.attention = Attention(hidden_size * 2)
        self.fc = nn.Linear(hidden_size * 2, output_size)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x):
        h0 = torch.zeros(self.num_layers * 2, x.size(0), self.hidden_size).to(x.device)
        c0 = torch.zeros(self.num_layers * 2, x.size(0), self.hidden_size).to(x.device)
        lstm_output, _ = self.lstm(x, (h0, c0))
        attn_output = self.attention(lstm_output)
        out = self.fc(self.dropout(attn_output))
        return out


class MduChpController(MappedController):
    """Pure prediction model controller using LSTM to predict MDU CHP thermal and electrical power output"""
    
    @classmethod
    def name(cls):
        return "mdu_chp_control"
    
    def name_class(self):
        return "mdu_chp_control"
    
    def __init__(self, container, mdu_chp_object, order=0, level=0, in_service=True, 
                 index=None, **kwargs):
        """Initialize MDU CHP controller
        
        :param container: Prosumer container object
        :param mdu_chp_object: MDU CHP data object
        :param order: Controller order
        :param level: Controller level
        :param in_service: Whether the controller is in service
        :param index: Controller index
        """
        super().__init__(container, mdu_chp_object, order, level, in_service, 
                        index, **kwargs)
        self.applied = None
        self._init_model()

    def _init_model(self):
        try:
            self.model = BiLSTMAttnRegressor(
                input_size=4,
                hidden_size=10,
                output_size=2,
                num_layers=2,
                dropout=0.1
            )

            # Get the directory where this file is located (controller/models/)
            current_dir = os.path.dirname(__file__)
            model_path = os.path.join(current_dir, "model_weights.pkl")
            scalers_path = os.path.join(current_dir, "scalers.pkl")

            self.model.load_state_dict(joblib.load(model_path))
            self.model.eval()

            scalers = joblib.load(scalers_path)
            self.input_scaler = scalers['input_scaler']
            self.target_scaler = scalers['target_scaler']

        except Exception as e:
            raise RuntimeError(f"Error initializing MDU CHP model: {str(e)}") from e

    def time_step(self, prosumer, time):
        """Initial call in each time step for preparation.

        :param prosumer:
        :param time:
        """
        super().time_step(prosumer, time)
        self.step_results = np.full([len(self.element_index), len(self.result_columns)], np.nan)
        self.time = time
        self.applied = False

    def is_converged(self, container):
        """Check if the controller has converged.

        :param container:
        :return: Convergence status
        """
        return self.applied

    def control_step(self, prosumer):
        """Implement LSTM prediction in control step"""
        try:
            # Get input data (raw values)
            size = float(self.inputs[0, self.input_columns.index("Size")])
            return_temp = float(self.inputs[0, self.input_columns.index("Return water temperature")])
            supply_temp = float(self.inputs[0, self.input_columns.index("Supply water temperature")])
            heat_demand = float(self.inputs[0, self.input_columns.index("Heat demand")])

            # Prepare model input for normalization
            input_data = np.array([[size, return_temp, supply_temp, heat_demand]])

            # Normalize input (transform to model's training range)
            scaled_input = self.input_scaler.transform(input_data)
            input_tensor = torch.FloatTensor(scaled_input).unsqueeze(1)

            # LSTM prediction (in normalized space)
            with torch.no_grad():
                predictions = self.model(input_tensor)
                # Denormalize predictions (back to original range)
                predictions = self.target_scaler.inverse_transform(predictions.numpy())

            # Extract predicted power (in MW from model)
            # q_fuel_mw: Total fuel heat input to CHP system
            # p_el_mw: Electrical power output (converted from fuel)
            q_fuel_mw = predictions[0, 0]
            p_el_mw = predictions[0, 1]
            
            # Set results
            result = np.zeros((1, len(self.result_columns)))
            result[0, self.result_columns.index("q_fuel_mw")] = q_fuel_mw
            result[0, self.result_columns.index("p_el_mw")] = p_el_mw
            
            # Calculate thermal output to heating network
            # Assuming: Q_fuel = thermal_output + electrical_output + losses
            # For simplicity, thermal_output ≈ heat_demand (CHP meets demand)
            # Use heat_demand as the actual thermal output to network
            thermal_output_kw = heat_demand
            
            # Calculate mass flow based on thermal output to heating network
            # Q = m * cp * ΔT
            # Get actual fluid cp from prosumer (same as Heat Demand will use)
            from pandaprosumer.constants import CELSIUS_TO_K
            t_mean_c = (supply_temp + return_temp) / 2
            cp_kj_per_kgk = float(prosumer.fluid.get_heat_capacity(CELSIUS_TO_K + t_mean_c)) / 1000
            
            delta_t = supply_temp - return_temp
            if delta_t > 0 and thermal_output_kw > 0:
                # Calculate mass flow from thermal output to network
                mdot_kg_per_s = thermal_output_kw / (cp_kj_per_kgk * delta_t)
            else:
                mdot_kg_per_s = 0
            
            # Get responders and create fluid mix result
            result_mdot_tab_kg_per_s = []
            if len(self._get_mapped_responders(prosumer)) > 0:
                # Distribute mass flow to responders based on their requirements
                mdot_required_tab_kg_per_s = []
                for responder in self._get_mapped_responders(prosumer):
                    _, _, mdot_required = responder.t_m_to_receive(prosumer)
                    mdot_required_tab_kg_per_s.append(mdot_required)
                
                # Use merit order to distribute available mass flow
                result_mdot_tab_kg_per_s = self._merit_order_mass_flow(
                    prosumer, 
                    mdot_kg_per_s, 
                    mdot_required_tab_kg_per_s
                )
            
            # Prepare fluid mix mapping data
            # Use the same keys as defined in FluidMixMapping class
            result_fluid_mix = []
            for mdot in result_mdot_tab_kg_per_s:
                result_fluid_mix.append({
                    FluidMixMapping.TEMPERATURE_KEY: supply_temp,  # Output temperature (°C)
                    FluidMixMapping.MASS_FLOW_KEY: mdot  # Mass flow (kg/s)
                })
            
            # Pass results to mapped controllers with fluid mix data
            self.finalize(prosumer, result, result_fluid_mix if result_fluid_mix else None)

        except Exception as e:
            raise RuntimeError(f"Error in MDU CHP control step: {str(e)}") from e

        self.applied = True
