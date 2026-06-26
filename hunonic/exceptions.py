"""
Custom exceptions for the Hunonic smart home client library.
"""


class HunonicError(Exception):
    """Base exception for all Hunonic errors."""
    pass


class HunonicAuthError(HunonicError):
    """Raised when authentication fails or token is invalid/expired."""
    pass


class HunonicConnectionError(HunonicError):
    """Raised when a network or connection error occurs."""
    pass


class HunonicDeviceError(HunonicError):
    """Raised when a device operation fails."""
    pass
