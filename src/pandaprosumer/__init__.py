# Copyright (c) 2025 by Fraunhofer Institute for Energy Economics
# and Energy System Technology (IEE), Kassel, and University of Kassel. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.

import importlib.metadata

__version__ = importlib.metadata.version("pandaprosumer")
__format_version__ = '0.1.0'

import pandas as pd
import os

pd.options.mode.chained_assignment = None  # default='warn'
pp_dir = os.path.dirname(os.path.realpath(__file__))
