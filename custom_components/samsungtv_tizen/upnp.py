#Smartthings TV integration#
import requests
import logging
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

_LOGGER = logging.getLogger(__name__)

# The TV takes seconds to accept a new media URI, unlike the volume polls
TRANSPORT_TIMEOUT = 15

DIDL_TEMPLATE = (
    '<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" '
    'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">'
    '<item id="0" parentID="-1" restricted="1"><dc:title>Stream</dc:title>'
    '<upnp:class>object.item.videoItem</upnp:class>'
    '<res protocolInfo="http-get:*:{mime}:*">{url}</res></item></DIDL-Lite>'
)

class upnp:

    def __init__(self, host):
        self.host = host
        self.mute = False
        self.volume = 0

    def __enter__(self):
        return self

    def SOAPrequest(self, action, arguments, protocole, timeout=0.1):
        headers = {'SOAPAction': '"urn:schemas-upnp-org:service:{protocole}:1#{action}"'.format(action=action, protocole=protocole), 'content-type': 'text/xml'}
        body = """<?xml version="1.0" encoding="utf-8"?>
                <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
                    <s:Body>
                    <u:{action} xmlns:u="urn:schemas-upnp-org:service:{protocole}:1">
                        <InstanceID>0</InstanceID>
                        {arguments}
                    </u:{action}>
                    </s:Body>
                </s:Envelope>""".format(action=action, arguments=arguments, protocole=protocole)
        response = None
        try:
            response = requests.post("http://{host}:9197/upnp/control/{protocole}1".format(host=self.host, protocole=protocole), data=body.encode("utf-8"), headers=headers, timeout=timeout)
            response = response.content
        except:
            pass
        return response

    def get_volume(self):
        response = self.SOAPrequest('GetVolume', "<Channel>Master</Channel>", 'RenderingControl')
        if response is not None:
            volume_xml = response.decode('utf8')
            tree = ET.fromstring(volume_xml)
            for elem in tree.iter(tag='CurrentVolume'):
                self.volume = elem.text
        return self.volume

    def set_volume(self, volume):
        self.SOAPrequest('SetVolume', "<Channel>Master</Channel><DesiredVolume>{}</DesiredVolume>".format(volume), 'RenderingControl')

    def get_mute(self):
        response = self.SOAPrequest('GetMute', "<Channel>Master</Channel>", 'RenderingControl')
        if response is not None:
            # mute_xml = response.decode('utf8')
            tree = ET.fromstring(response.decode('utf8'))
            mute = 0
            for elem in tree.iter(tag='CurrentMute'):
                mute = elem.text
            if (int(mute) == 0):
                self.mute = False
            else:
                self.mute = True
        return self.mute

    def set_current_media(self, url, mime=None):
        """ Set media to playback and play it."""
        if mime is None:
            mime = "application/vnd.apple.mpegurl" if ".m3u8" in url.lower() else "video/mp4"
        safe_url = escape(url)
        metadata = escape(DIDL_TEMPLATE.format(mime=mime, url=safe_url))
        self.SOAPrequest('Stop', "", 'AVTransport', TRANSPORT_TIMEOUT)
        for action, arguments in (
            ('SetAVTransportURI', "<CurrentURI>{}</CurrentURI><CurrentURIMetaData>{}</CurrentURIMetaData>".format(safe_url, metadata)),
            ('Play', "<Speed>1</Speed>"),
        ):
            response = self.SOAPrequest(action, arguments, 'AVTransport', TRANSPORT_TIMEOUT)
            if response is None or b"errorCode" in response:
                _LOGGER.error("Samsung TV rejected %s for %s: %s", action, url, response)
                return

    def stop(self):
        """ Stop the current DLNA playback."""
        response = self.SOAPrequest('Stop', "", 'AVTransport', TRANSPORT_TIMEOUT)
        if response is None or b"errorCode" in response:
            _LOGGER.error("Samsung TV rejected Stop: %s", response)

    def play(self):
        """ Play media that was already set as current."""
        try:
            self.SOAPrequest('Play', "<Speed>1</Speed>", 'AVTransport')
        except Exception:
            pass

