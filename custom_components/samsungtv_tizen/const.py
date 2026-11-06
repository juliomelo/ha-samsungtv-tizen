"""Constants for the samsungtv component."""

DOMAIN = "samsungtv_tizen"

CONF_MODEL = "model"
CONF_SHOW_CHANNEL_NR = "show_channel_number"
CONF_UPDATE_METHOD = "update_method"
CONF_UPDATE_CUSTOM_PING_URL = "update_custom_ping_url"
CONF_SOURCE_LIST = "source_list"
CONF_APP_LIST = "app_list"
CONF_CHANNEL_LIST = "channel_list"
CONF_SCAN_APP_HTTP = "scan_app_http"
CONF_IS_FRAME_TV = "is_frame_tv"
CONF_SHOW_LOGOS = "show_logos"

DEFAULT_NAME = "Samsung TV Remote"
DEFAULT_PORT = 8002
DEFAULT_TIMEOUT = 3
DEFAULT_UPDATE_METHOD = "ping"
DEFAULT_SOURCE_LIST = '{"TV": "KEY_TV", "HDMI": "KEY_HDMI"}'
DEFAULT_SHOW_LOGOS = "white-color"

PAIRING_TIMEOUT = 45

MEDIA_IMAGE_OPTIONS = {'none': 'none', 'bluecolor': '05a9f4-color', 'blue-white': '05a9f4-white', 'dark-white': '282c34-white', 'darkblue-white': '212c39-white', 'white-color': 'fff-color', 'transparent-color': 'transparent-color', 'transparent-white': 'transparent-white'}
