import os
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import joblib
from pandaprosumer.controller.base import BasicProsumerController



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


class IceChpController(BasicProsumerController):
    @classmethod
    def name(cls):
        return "ice_chp_control"

    def _init_model(self):
        try:
            self.model = BiLSTMAttnRegressor(
                input_size=4,
                hidden_size=10,
                output_size=2,
                num_layers=2,
                dropout=0.1
            )

            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            model_path = os.path.join(base_dir, "model_weights.pkl")
            scalers_path = os.path.join(base_dir, "scalers.pkl")

            self.model.load_state_dict(joblib.load(model_path))
            self.model.eval()

            scalers = joblib.load(scalers_path)
            self.input_scaler = scalers['input_scaler']
            self.target_scaler = scalers['target_scaler']

        except Exception as e:
            print(f"Error initializing model: {str(e)}")
            raise

    def _cycle(self):
        return self.inputs[:, self.input_columns.index("cycle")]

    def q_to_deliver_kw(self, prosumer):
        """Calculates the heat to deliver in kW.

        :param prosumer: The prosumer object
        :return: Heat to deliver in kW
        """
        q_to_deliver_kw = 0.
        for responder in self._get_mapped_responders(prosumer):
            q_to_deliver_kw += responder.q_to_receive_kw(prosumer)
        return q_to_deliver_kw

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
            # Get input data
            size = float(self.inputs[0, self.input_columns.index("Size")])
            return_temp = float(self.inputs[0, self.input_columns.index("Return water temperature")])
            supply_temp = float(self.inputs[0, self.input_columns.index("Supply water temperature")])
            heat_demand = float(self.inputs[0, self.input_columns.index("Heat demand")])

            # Prepare model input
            input_data = np.array([[size, return_temp, supply_temp, heat_demand]])

            # Normalize and predict
            scaled_input = self.input_scaler.transform(input_data)
            input_tensor = torch.FloatTensor(scaled_input).unsqueeze(1)

            with torch.no_grad():
                predictions = self.model(input_tensor)
                predictions = self.target_scaler.inverse_transform(predictions.numpy())

            # Set results
            self.step_results[0, self.result_columns.index("p_th_mw")] = predictions[0, 0]
            self.step_results[0, self.result_columns.index("p_el_mw")] = predictions[0, 1]

        except Exception as e:
            print(f"Error in control step: {str(e)}")
            raise

        self.applied = True

    @property
    def element_instance(self):
        """Get the element instance"""
        return self.component_object.element_index[0]

    def repair_control(self, container):
        """Attempt to fix convergence issues.

        :param container:
        """
        super().repair_control(container)

    def restore_init_state(self, container):
        """Restore initial state after control manipulations.

        :param container:
        """
        super().restore_init_state(container)

    def finalize_control(self, container):
        """Finalization logic after control execution.

        :param container:
        """
        super().finalize_control(container)

    def finalize_step(self, container, time):
        """Cleanup after each time step.

        :param container:
        :param time:
        """
        super().finalize_step(container, time)

    def set_active(self, container, in_service):
        """Set the controller in or out of service.

        :param container:
        :param in_service:
        """
        super().set_active(container, in_service)

    def level_reset(self, prosumer):
        """Reset the operational level.

        :param prosumer:
        """
        self.applied = False

    def time_series_initialization(self, prosumer):
        """Initialize time series data.

        :param prosumer:
        """
        return super().time_series_initialization(prosumer)

    def time_series_finalization(self, prosumer):
        """Finalize time series data.

        :param prosumer:
        """
        return self.res

    def initialize_control(self, container):
        """Extended initialization for the controller.

        :param container:
        """
        super().initialize_control(container)