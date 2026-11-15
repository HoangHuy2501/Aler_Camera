from copy import deepcopy
from datetime import UTC, datetime, timedelta
from importlib.util import find_spec
from pathlib import Path
from time import monotonic

import requests
from lxml import etree
from zeep import Client, Settings
from zeep.transports import Transport
from zeep.wsse.username import UsernameToken

from ingest import camera_endpoint
from security import decrypt

WSDL = Path(find_spec("onvif").origin).parent.parent / "wsdl"
EVENTS = "http://www.onvif.org/ver10/events/wsdl"
WSA = "http://www.w3.org/2005/08/addressing"
TRUE = {"true", "1", "on", "active", "start"}
FALSE = {"false", "0", "off", "inactive", "stop"}
STATE_FIELDS = {"state", "ismotion", "motion", "isperson", "person", "alarm", "active", "logicalstate", "isinside"}
EVENT_MARKERS = {
    "person": ("human", "person", "peopledetect", "videohuman"),
    "intrusion": ("intrusion", "fielddetector", "cellmotiondetector/regioninside"),
    "motion": ("motion",),
}


class LocalSession(requests.Session):
    def request(self, method, url, **kwargs):
        kwargs["allow_redirects"] = False
        return super().request(method, url, **kwargs)


def address(ref):
    return ref.Address._value_1


def snapshot_uri(client, capabilities, host):
    media = client("media.wsdl").create_service(
        "{http://www.onvif.org/ver10/media/wsdl}MediaBinding",
        camera_endpoint(capabilities.Media.XAddr, host),
    )
    profiles = media.GetProfiles()
    if not profiles:
        return None
    return media.GetSnapshotUri(ProfileToken=profiles[0].token).Uri


def read_event(message, inspect=None):
    topic = message.xpath("string(./*[local-name()='Topic'])").strip().lower()
    payload = message.xpath("./*[local-name()='Message']/*[local-name()='Message']")
    if not payload:
        return None
    raw = payload[0]
    data = {}
    for item in raw.xpath("./*[local-name()='Data']/*[local-name()='SimpleItem']"):
        if item.get("Name") and item.get("Value") is not None:
            data[item.get("Name").lower()] = item.get("Value").lower()
    if inspect:
        inspect(topic, sorted(data))
    operation = raw.get("PropertyOperation")
    if operation == "Initialized":
        return None
    classified = next(
        (kind for kind, names in EVENT_MARKERS.items()
         if any(name in topic or name in data for name in names)), None,
    )
    if classified is None:
        return None
    values = {value for name, value in data.items() if name in STATE_FIELDS or name == classified}
    if operation == "Deleted":
        state = False
    elif TRUE & values:
        state = True
    elif FALSE & values:
        state = False
    else:
        return None
    event_time = datetime.now(UTC)
    try:
        candidate = datetime.fromisoformat(raw.get("UtcTime", ""))
        if candidate.tzinfo:
            event_time = candidate
    except ValueError:
        pass
    sources = tuple(sorted(
        (item.get("Name", ""), item.get("Value", ""))
        for item in raw.xpath("./*[local-name()='Source']/*[local-name()='SimpleItem']")
    ))
    return classified, (topic, sources), state, event_time


def watch(camera, stopped, on_connected, on_event, inspect=None):
    host = camera["host"]
    username = camera["username"]
    password = decrypt(camera["secret"])
    with LocalSession() as session:
        session.trust_env = False
        transport = Transport(session=session, timeout=5, operation_timeout=15)
        wsse = UsernameToken(username, password, use_digest=True) if username else None

        def client(file):
            return Client(str(WSDL / file), transport=transport, wsse=wsse,
                          settings=Settings(strict=False, forbid_dtd=True))

        device = client("devicemgmt.wsdl").create_service(
            "{http://www.onvif.org/ver10/device/wsdl}DeviceBinding",
            f"http://{host}:{camera['port']}/onvif/device_service",
        )
        capabilities = device.GetCapabilities(Category="All")
        uri = None
        try:
            uri = snapshot_uri(client, capabilities, host)
        except Exception:
            # PullPoint can still work when Media or GetSnapshotUri is unavailable.
            pass
        events = client("events.wsdl")
        service = events.create_service(
            f"{{{EVENTS}}}EventBinding", camera_endpoint(capabilities.Events.XAddr, host),
        )
        subscription = service.CreatePullPointSubscription(InitialTerminationTime="PT120S")
        ref = subscription.SubscriptionReference
        endpoint = camera_endpoint(address(ref), host)
        headers = []
        if ref.ReferenceParameters:
            for element in ref.ReferenceParameters._value_1:
                header = deepcopy(element)
                header.set(f"{{{WSA}}}IsReferenceParameter", "true")
                headers.append(header)
        pull = events.create_service(f"{{{EVENTS}}}PullPointSubscriptionBinding", endpoint)
        manager = events.create_service(f"{{{EVENTS}}}SubscriptionManagerBinding", endpoint)
        states = {}
        try:
            renew_at = monotonic() + 35
            while not stopped.is_set():
                if monotonic() >= renew_at:
                    manager.Renew(TerminationTime="PT120S", _soapheaders=headers)
                    renew_at = monotonic() + 35
                with events.settings(raw_response=True):
                    response = pull.PullMessages(Timeout=timedelta(seconds=5), MessageLimit=20, _soapheaders=headers)
                response.raise_for_status()
                result = etree.fromstring(response.content, parser=etree.XMLParser(resolve_entities=False, no_network=True))
                body = result.find("{http://www.w3.org/2003/05/soap-envelope}Body")
                if body is None or body.find(f"{{{EVENTS}}}PullMessagesResponse") is None:
                    raise ValueError("Camera trả về bản tin PullMessages không hợp lệ.")
                if stopped.is_set():
                    break
                on_connected()
                for message in body.xpath("./*[local-name()='PullMessagesResponse']/*[local-name()='NotificationMessage']"):
                    event = read_event(message, inspect)
                    if event is None:
                        continue
                    kind, key, state, when = event
                    previous = states.get(key, (False, when))
                    if when < previous[1]:
                        continue
                    if state and (not previous[0] or when - previous[1] >= timedelta(seconds=30)):
                        on_event(kind, key, when, uri)
                        states[key] = (True, when)
                    elif not state:
                        states[key] = (False, when)
                stopped.wait(0.2)
        finally:
            try:
                manager.Unsubscribe(_soapheaders=headers)
            except Exception:
                pass
