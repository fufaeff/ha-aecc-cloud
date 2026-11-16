"""Base entity module for AECC Cloud integration."""
import logging

_LOGGER = logging.getLogger(__name__)


class BaseEntity:
    """Base class for AECC Cloud entities."""

    def __init__(self, hass, hub):
        self.hass = hass
        self.hub = hub
        self.unit = None
