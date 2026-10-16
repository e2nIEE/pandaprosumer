# Import pandaprosumer in the pytest-xdist controller process too. Each warning a worker emits
# (e.g. EnergyLeakWarning) is rebuilt in the controller by importing its module; without this
# preload, concurrent first imports of pandaprosumer.controller.models deadlock (_DeadlockError,
# INTERNALERROR) and abort the session.
import pandaprosumer.controller.models  # noqa: F401
