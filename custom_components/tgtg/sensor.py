"""Platform for TGTG sensor integration."""
from __future__ import annotations
import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional

import voluptuous as vol
from tgtg import TgtgClient

from homeassistant.components.sensor import SensorEntity, PLATFORM_SCHEMA
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_EMAIL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import (
    DOMAIN,
    CONF_ITEM,
    CONF_REFRESH_TOKEN,
    CONF_COOKIE,
    CONF_USER_AGENT,
    ATTR_ITEM_ID,
    ATTR_ITEM_URL,
    ATTR_PRICE,
    ATTR_VALUE,
    ATTR_PICKUP_START,
    ATTR_PICKUP_END,
    ATTR_SOLDOUT_TIMESTAMP,
    ATTR_ORDERS_PLACED,
    ATTR_TOTAL_QUANTITY_ORDERED,
    ATTR_PICKUP_WINDOW_CHANGED,
    ATTR_CANCEL_UNTIL,
    ATTR_LOGO_URL,
    ATTR_COVER_URL,
    DEFAULT_UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_ACCESS_TOKEN): cv.string,
        vol.Required(CONF_REFRESH_TOKEN): cv.string,
        vol.Required(CONF_COOKIE): cv.string,
        vol.Optional("user_id"): cv.string,
        vol.Optional(CONF_EMAIL): vol.Email(),
        vol.Optional(CONF_ITEM, default=""): cv.ensure_list,
        vol.Optional(CONF_USER_AGENT, default=""): cv.string,
    }
)


def create_tgtg_client(access_token, refresh_token, cookie, user_agent):
    """Create a TGTG client instance."""
    return TgtgClient(
        access_token=access_token,
        refresh_token=refresh_token,
        cookie=cookie,
        user_agent=user_agent,
    )


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the TGTG sensor platform."""
    email = config.get(CONF_EMAIL)
    item = config.get(CONF_ITEM, [""])
    access_token = config[CONF_ACCESS_TOKEN]
    refresh_token = config[CONF_REFRESH_TOKEN]
    cookie = config[CONF_COOKIE]
    user_agent = config.get(CONF_USER_AGENT, "")

    # Initialize the TGTG client in an executor to prevent blocking the event loop
    tgtg_client = await hass.async_add_executor_job(
        create_tgtg_client, access_token, refresh_token, cookie, user_agent
    )

    # Initialize the coordinator
    coordinator = TGTGDataUpdateCoordinator(hass, tgtg_client, item)
    
    # Fetch initial data
    await coordinator.async_refresh()
    
    # Create entities
    entities = []

    # Create entities based on the data from the coordinator
    if item != [""]:
        # Use specified items
        for item_id in item:
            if item_id in coordinator.data:
                entities.append(TGTGSensor(coordinator, item_id))
    else:
        # Use favorites
        try:
            for item_id in coordinator.data:
                if item_id != "orders":
                    entities.append(TGTGSensor(coordinator, item_id))
        except (KeyError, TypeError):
            _LOGGER.error("Failed to get items from TGTG API")

    add_entities(entities)


class TGTGDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching TGTG data."""

    def __init__(
        self, hass: HomeAssistant, tgtg_client: TgtgClient, items: List[str]
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=DEFAULT_UPDATE_INTERVAL),
        )
        self.tgtg_client = tgtg_client
        self.items = items

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from TGTG API."""
        try:
            data = {}
            
            # Get active orders - we'll do this only once for all sensors
            _LOGGER.info("GET ORDERS")
            orders = ""
            data["orders"] = ""
            
            # Get items data
            if self.items != [""]:
                # Fetch specified items
                _LOGGER.info("GET SPECIFIC ITEM")
                for item_id in self.items:
                    item_data = await self.hass.async_add_executor_job(
                        self.tgtg_client.get_item, item_id
                    )
                    data[item_id] = item_data
            else:
                # Fetch favorites
                _LOGGER.info("GET FAVORITES")
                favorites = await self.hass.async_add_executor_job(
                    self.tgtg_client.get_favorites 
                )
                for item in favorites:
                    item_id = item["item"]["item_id"]
                    data[item_id] = item
            
            return data
        except Exception as err:
            raise UpdateFailed(f"Error communicating with TGTG API: {err}")


class TGTGSensor(CoordinatorEntity, SensorEntity):
    """Representation of a TGTG Sensor."""

    def __init__(self, coordinator: TGTGDataUpdateCoordinator, item_id: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.item_id = item_id
        self._store_name = self.coordinator.data[item_id]["display_name"]
        
    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return f"TGTG {self._store_name}"

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"tgtg_{self.item_id}"

    @property
    def icon(self) -> str:
        """Return an icon."""
        return "mdi:storefront-outline"

    @property
    def unit_of_measurement(self) -> str:
        """Return the unit of measurement."""
        return "pcs"

    @property
    def native_value(self) -> int:
        """Return the state of the sensor."""
        try:
            return self.coordinator.data[self.item_id]["items_available"]
        except (KeyError, TypeError):
            return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return the optional state attributes."""
        try:
            tgtg_answer = self.coordinator.data[self.item_id]
            tgtg_orders = self.coordinator.data.get("orders", [])
            
            data = {}
            if "item" in tgtg_answer:
                if "item_id" in tgtg_answer["item"]:
                    data[ATTR_ITEM_ID] = tgtg_answer["item"]["item_id"]
                    data[ATTR_ITEM_URL] = "https://share.toogoodtogo.com/item/" + str(
                        tgtg_answer["item"]["item_id"]
                    )
                if "item_price" in tgtg_answer["item"]:
                    data[ATTR_PRICE] = (
                        str(
                            int(tgtg_answer["item"]["item_price"]["minor_units"])
                            / pow(10, int(tgtg_answer["item"]["item_price"]["decimals"]))
                        )
                        + " "
                        + tgtg_answer["item"]["item_price"]["code"]
                    )
                if "item_value" in tgtg_answer["item"]:
                    data[ATTR_VALUE] = (
                        str(
                            int(tgtg_answer["item"]["item_value"]["minor_units"])
                            / pow(10, int(tgtg_answer["item"]["item_value"]["decimals"]))
                        )
                        + " "
                        + tgtg_answer["item"]["item_value"]["code"]
                    )

                if "logo_picture" in tgtg_answer["item"]:
                    data[ATTR_LOGO_URL] = tgtg_answer["item"]["logo_picture"]["current_url"]
                if "cover_picture" in tgtg_answer["item"]:
                    data[ATTR_COVER_URL] = tgtg_answer["item"]["cover_picture"]["current_url"]

            if "pickup_interval" in tgtg_answer:
                if "start" in tgtg_answer["pickup_interval"]:
                    data[ATTR_PICKUP_START] = tgtg_answer["pickup_interval"]["start"]
                if "end" in tgtg_answer["pickup_interval"]:
                    data[ATTR_PICKUP_END] = tgtg_answer["pickup_interval"]["end"]
            if "sold_out_at" in tgtg_answer:
                data[ATTR_SOLDOUT_TIMESTAMP] = tgtg_answer["sold_out_at"]

            orders_placed = 0
            total_quantity_ordered = 0
            for order in tgtg_orders:
                if "item_id" in order:
                    if order["item_id"] == str(self.item_id):
                        orders_placed += 1
                        if "quantity" in order:
                            total_quantity_ordered += order["quantity"]
                        if "pickup_window_changed" in order:
                            data[ATTR_PICKUP_WINDOW_CHANGED] = order["pickup_window_changed"]
                        if "cancel_until" in order:
                            data[ATTR_CANCEL_UNTIL] = order["cancel_until"]
            data[ATTR_ORDERS_PLACED] = orders_placed
            if total_quantity_ordered > 0:
                data[ATTR_TOTAL_QUANTITY_ORDERED] = total_quantity_ordered
            return data
        except (KeyError, TypeError):
            return {}
