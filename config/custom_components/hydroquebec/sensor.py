import logging
import asyncio
import json

from datetime import datetime, timedelta
from dateutil import tz, relativedelta

from pyhydroquebec.error import PyHydroQuebecHTTPError
from pyhydroquebec.client import HydroQuebecClient
from pyhydroquebec.consts import (
    CURRENT_MAP,
    DAILY_MAP,

)

import voluptuous as vol

from homeassistant.exceptions import PlatformNotReady
from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import (
    CONF_USERNAME,
    CONF_PASSWORD,
    ENERGY_KILO_WATT_HOUR,
    CONF_NAME,
    CONF_MONITORED_VARIABLES,
    TEMP_CELSIUS,
)
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import Throttle
import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)

REQUESTS_TIMEOUT = 15
MIN_TIME_BETWEEN_UPDATES = timedelta(hours=6)
SCAN_INTERVAL = timedelta(hours=6)

CONF_CONTRACT = "contract"
CONF_NAME = "name"
CONF_MONITORED_VARIABLES = "monitored_variables"

KILOWATT_HOUR = ENERGY_KILO_WATT_HOUR
SENSOR_TYPES = {**CURRENT_MAP, **DAILY_MAP}

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
        vol.Required(CONF_CONTRACT): cv.string,
        vol.Optional(CONF_NAME): cv.string,
        vol.Optional(CONF_MONITORED_VARIABLES, default=[]): vol.All(
            cv.ensure_list, [vol.In(SENSOR_TYPES)]
        ),
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the HydroQuebec sensor."""
    # Create a data fetcher to support all of the configured sensors. Then make
    # the first call to init the data.

    _LOGGER.debug("Création du client")

    username = config.get(CONF_USERNAME)
    password = config.get(CONF_PASSWORD)
    contract = config.get(CONF_CONTRACT)
    monitored_variables = config.get(CONF_MONITORED_VARIABLES)
    time_zone = str(hass.config.time_zone)
    httpsession = async_get_clientsession(hass, False)

    hqdata = HydroQuebecData(
        username, password, contract, time_zone, REQUESTS_TIMEOUT, httpsession  # , 'DEBUG'
    )

    await hqdata.async_update()

    sensors = []
    for sensor_type in monitored_variables:
        sensors.append(HydroQuebecSensor(hqdata, sensor_type))

    async_add_entities(sensors, True)
    return True


class HydroQuebecSensor(Entity):
    """Implementation of a HydroQuebec sensor."""

    def __init__(self, hqdata, sensor_type):
        """Initialize the sensor."""
        self.type = sensor_type
        self._client_name = "hydroquebec"
        self._name = SENSOR_TYPES[sensor_type]["raw_name"]
        self._unit_of_measurement = SENSOR_TYPES[sensor_type]["unit"]
        self._icon = SENSOR_TYPES[sensor_type]["icon"]
        self._device_class = SENSOR_TYPES[sensor_type]["device_class"]
        self.hqdata = hqdata
        self._state = None
        self._unique_id = f"{sensor_type}_{self._name}"

        _LOGGER.debug(f"init sensor {sensor_type}")

    @property
    def name(self):
        """Return the name of the sensor."""
        return f"{self._name}"

    @property
    def state(self):
        """Return the state of the sensor."""
        if self.type[0:5] == "perio":
            if self.hqdata.period != {}:
                return "{:.2f}".format(self.hqdata.period[self.type])
            else:
                return None
        else:
            if self.hqdata.daily != {}:
                return "{:.2f}".format(self.hqdata.daily[self.type])
            else:
                return None

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement of this entity, if any."""
        return self._unit_of_measurement

    @property
    def icon(self):
        """Icon to use in the frontend, if any."""
        return self._icon

    @property
    def device_class(self):
        """Home-Assistant device class"""
        return self._device_class

    @property
    def unique_id(self):
        return self._unique_id

    async def async_update(self):
        """Get the latest data from Hydroquebec and update the state."""

        await self.hqdata.async_update()

        # _LOGGER.debug(self._hqdata.period)


class HydroQuebecData:
    """Implementation of a HydroQuebec DataConnector."""

    def __init__(self, username, password, contract, time_zone, REQUESTS_TIMEOUT, httpsession):
        self._contract = contract
        self._hqclient = HydroQuebecClient(
            username, password, REQUESTS_TIMEOUT, httpsession  # , 'DEBUG'
        )
        self._daily = {}
        self._period = {}
        self._tz = tz.gettz(time_zone)

    @property
    def daily(self):
        return self._daily

    @property
    def period(self):
        return self._period

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    async def async_update(self):
        """Get the latest data from Hydroquebec and update the state."""

        await self._hqclient.login()
        for customer in self._hqclient.customers:
            if customer.contract_id != self._contract and self._contract is not None:
                continue
            if self._contract is None:
                _LOGGER.warning(
                    "Contract id not specified, using first available.")

            try:

                yesterday = datetime.now(self._tz) - timedelta(hours=27)
                yesterday_str = yesterday.strftime("%Y-%m-%d")
                _LOGGER.debug(f"Fetching: {yesterday_str}")

                await customer.fetch_daily_data(yesterday_str, yesterday_str)
                await customer.fetch_current_period()

                curr = customer.current_daily_data
                #yesterday_date = list(curr.keys())[0]
                self._daily = curr[yesterday_str]

                period = customer.current_period
                self._period = period

            except Exception as e:

                _LOGGER.warning(f"Exception: {e}")

            return
