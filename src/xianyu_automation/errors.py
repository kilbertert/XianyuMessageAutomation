class AutomationError(RuntimeError):
    """Base exception for expected automation failures."""


class ConfigurationError(AutomationError):
    """Raised when configuration is invalid."""


class DeviceStateError(AutomationError):
    """Raised when the Android device is not in the expected state."""
