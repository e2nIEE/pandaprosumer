import pandas as pd
import numpy as np


# CSV-Datei einlesen
dummy_data = pd.read_csv("C:\\Users\\carl\\Downloads\\strompreis.csv",
                          parse_dates=["Datetime"],
                          index_col="Datetime" )

dummy_data.drop(columns="Stromhandelsbilanz", inplace=True)

dummy_data.rename(columns={"Strompreis": "Strompreis EUR/MWh"}, inplace=True)

dummy_data["Strompreis EUR/MWh"] += 100 # €/MWh :Kosten für Stronmsteuer, Netzentgelte etc. Auf den Börsenpreis addiert.

dummy_data["Gaspreis EUR/MWh"] = 70

n_sections = 12
n = len(dummy_data)

# Zufallswerte für jede Sektion
random_values = np.random.randint(-500, 501, size=n_sections)

# Spalte erstellen: np.repeat, dann ggf. Rest auffüllen
section_size = n // n_sections
repeated_values = np.repeat(random_values, section_size)

# Restzeilen auffüllen, falls nötig
rest = n - len(repeated_values)
if rest > 0:
    repeated_values = np.concatenate([repeated_values, np.full(rest, random_values[-1])])

dummy_data["Flexibility Demand kW"] = repeated_values

print(dummy_data)

