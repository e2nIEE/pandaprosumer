"""
Controller messaging service for standardized warnings and errors.
"""

import logging
from datetime import datetime
from typing import Optional, Type, Dict, Any
import numpy as np


class ControllerMessaging:
    """
    Standalone messaging service that provides standardized warning and error formatting
    for prosumer controllers.
    """

    def __init__(self, controller):
        """
        Initialize the messaging service with a controller reference.

        Args:
            controller: The controller instance that will use this service
        """
        self.controller = controller
        self.logger = logging.getLogger(controller.__class__.__module__)

    def warn(self, message: str) -> str:
        """
        Issue a standardized warning message.

        Args:
            message: The core warning message

        Returns:
            The formatted warning message
        """
        context = self._get_context()
        formatted = self._format_message(message, "WARNING", context)
        self.logger.warning(formatted)
        return formatted

    def error(self, message: str, error_class: Type[Exception] = ValueError) -> None:
        """
        Issue a standardized error and raise an exception.

        Args:
            message: The core error message
            error_class: Exception class to raise (default: ValueError)

        Raises:
            The specified exception class with formatted message
        """
        context = self._get_context()
        formatted = self._format_message(message, "ERROR", context)
        self.logger.error(formatted)
        raise error_class(formatted)

    def assert_condition(
        self,
        condition: bool,
        message: str,
        error_class: Type[Exception] = ValueError,
        include_traceback: bool = False
    ) -> None:
        """
        Assert a condition with standardized error message if false.

        Args:
            condition: Condition to check
            message: Error message if condition is false
            error_class: Exception class to raise
            include_traceback: Whether to include traceback in error

        Raises:
            The specified exception if condition is false
        """
        if not condition:
            context = self._get_context()
            formatted = self._format_message(message, "ERROR", context, include_traceback)
            self.logger.error(formatted)
            raise error_class(formatted)

    def assert_not_nan(self, value: Any, name: str, error_class: Type[Exception] = ValueError) -> None:
        """
        Assert that a value is not NaN.

        Args:
            value: The value to check
            name: Name of the value for error message
            error_class: Exception class to raise

        Raises:
            The specified exception if value is NaN
        """
        if isinstance(value, (float, np.floating)) and np.isnan(value):
            self.error(f"{name} is NaN", error_class)
        elif isinstance(value, (np.ndarray, list)) and any(np.isnan(val) for val in value):
            self.error(f"{name} contains NaN values", error_class)

    def assert_positive(self, value: Any, name: str, error_class: Type[Exception] = ValueError) -> None:
        """
        Assert that a value is positive.

        Args:
            value: The value to check
            name: Name of the value for error message
            error_class: Exception class to raise

        Raises:
            The specified exception if value is not positive
        """
        if value < 0:
            self.error(f"{name} is negative: {value}", error_class)

    def assert_greater_equal(self, value1: Any, value2: Any, name1: str, name2: str, error_class: Type[Exception] = ValueError) -> None:
        """
        Assert that value1 >= value2.

        Args:
            value1: First value
            value2: Second value
            name1: Name of first value
            name2: Name of second value
            error_class: Exception class to raise

        Raises:
            The specified exception if value1 < value2
        """
        if value1 < value2:
            self.error(f"{name1} ({value1}) is less than {name2} ({value2})", error_class)

    def _get_context(self) -> Dict[str, Any]:
        """
        Extract context information from the controller.

        Returns:
            Dictionary containing context information
        """
        return {
            'real_timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'simulation_time': getattr(self.controller, 'time', None),
            'prosumer': getattr(self.controller.prosumer, 'name', 'Unknown') if hasattr(self.controller, 'prosumer') else 'Unknown',
            'model': self.controller.__class__.__name__.replace('Controller', ''),
            'controller': getattr(self.controller, 'name', 'Unnamed')
        }

    def _format_message(self, message: str, level: str, context: Dict[str, Any], include_traceback: bool = False) -> str:
        """
        Format a message with standardized context.

        Args:
            message: The core message
            level: Message level (WARNING, ERROR, etc.)
            context: Context dictionary
            include_traceback: Whether to include traceback

        Returns:
            Formatted message string
        """
        # Build context components
        components = [
            f"[{context['real_timestamp']}]",
            f"[SIM: {context['simulation_time'] or 'Not started'}]",
            f"[PROSUMER: {context['prosumer']}]",
            f"[MODEL: {context['model']}]",
            f"[CONTROLLER: {context['controller']}]"
        ]

        # Format the full message
        full_message = " ".join(components) + f" {level}: {message}"

        # Add traceback if requested
        if include_traceback and level == "ERROR":
            import traceback
            tb = "".join(traceback.format_stack()[:-1])  # Exclude this function call
            full_message += f"\nTRACEBACK:\n{tb}"

        return full_message