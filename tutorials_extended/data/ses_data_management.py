# -*- coding: utf-8 -*-
"""
SES PRESENTATION & PAPER

mkeber (13-07-2026)

DATA MANAGEMENT LAYER

::::::::::::::::::::::::::::::::::::::

Input data for the pandaprosumer model:

    - All data is in the 'ses_data_df' dataframe

    - Relevant columns for model testing:

        - P el total [kW] ---> total electrical demand (for the demand element)

        - P pv [kW] ---> PV data

        - P el contr [kW] ---> internal flexibility ---> data for the first flexibility test of the model

        - P flex total [kW] ---> total flexibility ---> to be tested at the end

"""

# ESSENTIAL IMPORTS ---> don't change
import os
import pandas as pd
import matplotlib.pyplot as plt

# Kernel path ---> check; not important ---> can be removed
#import sys
#print(sys.executable)

# SETTING THE PATH TO THE PANDAPROSUMER SOURCE ---> change to your setup or remove
from pathlib import Path
from pathlib import Path

data_dir = Path(__file__).resolve().parent
demand_data_file = data_dir / "ses_data.xlsx"

print(
    "Reading SES data from:",
    demand_data_file
)

if not demand_data_file.exists():
    raise FileNotFoundError(
        f"Excel file not found: {demand_data_file}"
    )

ses_data_df = pd.read_excel(
    demand_data_file,
    index_col=0,
)

ses_data_df.index = pd.to_datetime(
    ses_data_df.index
)

ses_data_df = ses_data_df.sort_index()

print(ses_data_df.head())                        # THE MAIN DATAFRAME ---> use 'ses_data_df' as the input for the pandaprosumer model


# EV power requirements
# Assumptions:
# - MCS (Megawatt Charging System)
# - Charging power: 1-1.2 MW
# - Theoretical max. charging power: 3.75 MW
# - Battery capacities: 600-1000 kWh
# - CCS chargers: 350 kW
p_el_mcscharge_max_kw = 1000            # max. MCS charging power of the system ---> charging power per charger
p_el_ccscharge_max_kw = 350             # max. CCS charging power of the system ---> charging power per charger

n_charger = 3                           # number of chargers at loading bays

p_el_charge_kw = p_el_mcscharge_max_kw * n_charger    # total charging power at the shopping centre

# Chargin times
t_ev_charge_start1 = "06:00"
t_ev_charge_end1 = "10:00"
#
t_ev_charge_start2 = "08:00"
t_ev_charge_end2 = "11:00"

# Charging schedule
schedule_ev_charging = {
 #day: [(start time, end time, power)]
    0: [(t_ev_charge_start1, t_ev_charge_end1, p_el_charge_kw)],   # Monday
    1: [(t_ev_charge_start1, t_ev_charge_end1, p_el_charge_kw)],   # Tuesday
    2: [(t_ev_charge_start1, t_ev_charge_end1, p_el_charge_kw)],   # Wednesday
    3: [(t_ev_charge_start1, t_ev_charge_end1, p_el_charge_kw)],   # Thursday
    4: [(t_ev_charge_start1, t_ev_charge_end1, p_el_charge_kw)],   # Friday
    5: [(t_ev_charge_start2, t_ev_charge_end2, p_el_charge_kw)],   # Saturday
    #6: [(t_ev_charge_start2, t_ev_charge_end2, p_el_charge_kw)],   # Sunday
}

ses_data_df["P ev [kW]"] = 0.0                              # adding a column to the input dataframe ---> EV charging power requirement

# Fills the dataframe with the EV charging power requirements
for day, periods in schedule_ev_charging.items():
    for start, end, power in periods:
        start_time = pd.to_datetime(start).time()
        end_time = pd.to_datetime(end).time()

        mask = (
            (ses_data_df.index.dayofweek == day) &
            (ses_data_df.index.time >= start_time) &
            (ses_data_df.index.time < end_time)
        )

        ses_data_df.loc[mask, "P ev [kW]"] = power


# Total elelctrical power demand ---> shopping centre power + EV charge power
ses_data_df["P el total [kW]"] = ses_data_df["P el sc [kW]"] + ses_data_df["P ev [kW]"]


# External flexibility
# Assumptions:
# - Step change only
# - Negative values for flexibilty to represent the DSO's request
p_el_flex_kw = 700

ses_data_df["P el flex [kW]"] = 0.0                        # adding a column to the input dataframe ---> external flexibility

# Days and times for external flexibility
schedule_flex = {
    #(start date & time, end date &time, power)]
    ("2025-07-08 08:00", "2025-07-08 10:00", p_el_flex_kw),
    ("2025-07-09 08:00", "2025-07-09 09:00", p_el_flex_kw),
    ("2025-07-10 08:00", "2025-07-10 10:00", p_el_flex_kw)
}

# Fills the dataframe with external flexibility data
for start, end, value in schedule_flex:
    ses_data_df.loc[start:end, "P el flex [kW]"] = p_el_flex_kw


# Total flexibility requirement:
# Total flexibility = internal flexibility + external flexibility
#ses_data_df["P flex total [kW]"] = ses_data_df["P el contr [kW]"] + ses_data_df["P el flex [kW]"]
ses_data_df["P grid baseline [kW]"] = (ses_data_df["P el total [kW]"] - ses_data_df["P pv [kW]"])

ses_data_df["P grid target [kW]"] = (ses_data_df["P grid baseline [kW]"] - ses_data_df["P el flex [kW]"])
#===================================================================================================

# PLOTTING DATAFRAMES:
ses_data_df_subset = ses_data_df.loc["2025-07-08" : "2025-07-10"]

fig, ax = plt.subplots(figsize=(10, 5))
#
ax.plot(ses_data_df_subset.index, ses_data_df_subset["P el total [kW]"], label="P el total [kW]")
#ax.plot(ses_data_df_subset.index, ses_data_df_subset["P el sc [kW]"], label="P el sc [kW]")
ax.plot(ses_data_df_subset.index, ses_data_df_subset["P el contr [kW]"], label="P el contr [kW]")
#ax.plot(ses_data_df_subset.index, ses_data_df_subset["P pv [kW]"], label="P pv [kW]")
ax.plot(ses_data_df_subset.index, ses_data_df_subset["P grid baseline [kW]"], label="Baseline grid import")
ax.plot(ses_data_df_subset.index, ses_data_df_subset["P grid target [kW]"], label="Requested grid target")
ax.set_ylabel("P [kW]")
ax.set_title("Shopping centre + EV consumption + flexibility")
#
ax.legend(
    loc="upper center",
    bbox_to_anchor=(0.5, -0.22),
    ncol=5,
    frameon=False
)
#
fig.subplots_adjust(bottom=0.25)
plt.show()


fig, ax = plt.subplots(figsize=(10, 5))
#
ax.plot(ses_data_df.index, ses_data_df["P el sc [kW]"], label="P el sc [kW]")
ax.plot(ses_data_df.index, ses_data_df["P el contr [kW]"], label="P el contr [kW]")
#ax.plot(ses_data_df_subset.index, ses_data_df_subset["P pv [kW]"], label="P pv [kW]")
#ax.plot(ses_data_df_subset.index, ses_data_df_subset["P flex total [kW]"], linestyle="--", linewidth=2, label="P flex total [kW]")    # dashed line
#
ax.set_ylabel("P [kW]")
#ax.set_title("Shopping centre")
#
ax.legend(
    loc="upper center",
    bbox_to_anchor=(0.5, -0.1),
    ncol=5,
    frameon=False
)
#
fig.subplots_adjust(bottom=0.25)
plt.show()
