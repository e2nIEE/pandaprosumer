"""
Structural validation of the controller/mapping graph of a prosumer.

These checks run once, before a time series simulation starts, so that an
ill-connected network fails immediately with an explicit, actionable message
instead of crashing deep inside the control loop with an opaque ``KeyError``
or ``IndexError`` (e.g. a controller that needs an initiator or a responder
but doesn't have one).
"""

from warnings import warn
import logging as pplog

logger = pplog.getLogger(__name__)


class OrphanedControllerWarning(UserWarning):
    """
    Raised when a controller takes part in a network that has mappings, yet is
    itself referenced by no mapping (neither as an initiator nor as a
    responder). Such a controller can neither receive inputs from nor deliver
    its results to any other controller, which is almost always a wiring
    mistake.

    Filter with ``warnings.simplefilter("ignore", OrphanedControllerWarning)``
    if a standalone controller is intentional.
    """
    pass


# Controllers that are not expected to be wired to other controllers and so
# should never be flagged as orphaned. ``const_profile_control`` only feeds
# time-series data into the network and may legitimately stand alone.
_ORPHAN_EXEMPT_CLASSES = ("const_profile_control",)


def _controller_label(net, idx):
    """Return a human-readable ``#idx ('name')`` label for a controller index."""
    try:
        obj = net.controller.loc[idx, "object"]
        name = getattr(obj, "name", None)
        return f"#{idx} ('{name}')" if name else f"#{idx}"
    except (KeyError, AttributeError):
        return f"#{idx}"


def _existing_controllers_hint(net):
    """Return a string listing the controller indices and names that do exist."""
    if not hasattr(net, "controller") or len(net.controller) == 0:
        return "the network has no controller at all"
    labels = [_controller_label(net, idx) for idx in net.controller.index]
    return "existing controllers: " + ", ".join(labels)


def check_controller_connections(container):
    """
    Validate that every mapping of ``container`` points to controllers that
    actually exist, and warn about controllers that are left unconnected.

    :param container: The prosumer (or compatible container) object to check
    :raises ValueError: If a mapping references an initiator or a responder
        controller index that does not exist in the relevant network.
    """
    if not hasattr(container, "mapping") or len(container.mapping) == 0:
        # No mapping at all (e.g. a single-controller setup): nothing to wire,
        # nothing to check.
        return
    if not hasattr(container, "controller") or len(container.controller) == 0:
        return

    container_name = getattr(container, "name", "<unnamed>")
    errors = []
    referenced = set()

    for mapping_idx, row in container.mapping.iterrows():
        mapping_obj = row["object"]
        initiator_id = row["initiator"]
        responder_id = row["responder"]
        mapping_name = getattr(mapping_obj, "name", type(mapping_obj).__name__)
        initiator_net = getattr(mapping_obj, "initiator_net", container)
        responder_net = getattr(mapping_obj, "responder_net", container)

        referenced.add(initiator_id)
        # Only count the responder as "connected within this container" when it
        # lives in the same network; cross-network responders belong to another
        # container and shouldn't suppress an orphan warning here.
        if responder_net is container:
            referenced.add(responder_id)

        if not hasattr(initiator_net, "controller") or initiator_id not in initiator_net.controller.index:
            errors.append(
                f"  - mapping #{mapping_idx} ({mapping_name}): initiator controller "
                f"#{initiator_id} does not exist ({_existing_controllers_hint(initiator_net)})."
            )
        if not hasattr(responder_net, "controller") or responder_id not in responder_net.controller.index:
            errors.append(
                f"  - mapping #{mapping_idx} ({mapping_name}): responder controller "
                f"#{responder_id} does not exist ({_existing_controllers_hint(responder_net)})."
            )

    if errors:
        raise ValueError(
            f"Invalid controller mapping(s) in prosumer '{container_name}': a mapping "
            f"references a controller that does not exist. This usually means the "
            f"mapping was created with a wrong controller index, or the controller it "
            f"points to was never created.\n" + "\n".join(errors)
        )

    # Warn about controllers that are part of a mapped network but are wired to
    # nothing: they can neither be fed by an initiator nor deliver to a responder.
    for idx in container.controller.index:
        ctrl = container.controller.loc[idx, "object"]
        if idx in referenced:
            continue
        if getattr(ctrl, "name_class", lambda: "")() in _ORPHAN_EXEMPT_CLASSES:
            continue
        if hasattr(ctrl, "is_supervisor") and ctrl.is_supervisor():
            continue
        warn(
            f"Controller {_controller_label(container, idx)} in prosumer "
            f"'{container_name}' is not connected to any other controller: no mapping "
            f"uses it as an initiator or a responder. It will neither receive inputs "
            f"from nor deliver its results to another controller. Add a mapping "
            f"(create_..._mapping) if this controller is meant to be connected.",
            OrphanedControllerWarning,
            stacklevel=2,
        )
