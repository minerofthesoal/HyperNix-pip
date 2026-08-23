"""hypernix.hyperlink — HyperNix from a phone, on or off the home network.

New in **T1 v1.0.26.8.0.1**. HyperLink is the layer that lets the iOS
app (``ios/HyperLink``) treat a home PC as its inference backend: pair
once, then chat, send photos, upload files, read code, and download
GGUF models, whether the phone is on the same Wi-Fi or on cellular
across Tailscale.

Five pieces, each usable on its own:

* :mod:`~hypernix.hyperlink.pairing` — six-character pairing codes that
  become per-device tokens. The enrolment path that makes a 48-character
  T1 key unnecessary on a phone keyboard.
* :mod:`~hypernix.hyperlink.sessions` — server-side conversations, so a
  thread started on the laptop continues on the phone.
* :mod:`~hypernix.hyperlink.files` — a content-addressed attachment
  store for images, documents and code.
* :mod:`~hypernix.hyperlink.hfmerge` — turn a Hugging Face model page
  and/or a direct download link into a complete, runnable GGUF download
  plan (split parts and vision projectors included).
* :mod:`~hypernix.hyperlink.discovery` — enumerate the addresses this
  machine is reachable at, ranked, so the phone can pick one.

Standard library only, and importable without the ``hypernix[t1api]``
extra: the HTTP surface lives in ``t1api/routers/hyperlink.py``, and
everything here is testable with no web layer in the way.
"""
from __future__ import annotations

from .discovery import Endpoint, advertise, local_endpoints
from .files import Attachment, AttachmentStore
from .hfmerge import HFRef, HFResolveError, ResolvedModel, merge, parse_link, resolve
from .pairing import DeviceRecord, DeviceRegistry, PairingCode, pairing_payload
from .sessions import ChatMessage, ChatSession, ChatSessionStore

__hyperlink_version__ = "1.0.26.8.0.1"

__all__ = [
    "__hyperlink_version__",
    "Attachment",
    "AttachmentStore",
    "ChatMessage",
    "ChatSession",
    "ChatSessionStore",
    "DeviceRecord",
    "DeviceRegistry",
    "Endpoint",
    "HFRef",
    "HFResolveError",
    "PairingCode",
    "ResolvedModel",
    "advertise",
    "local_endpoints",
    "merge",
    "pairing_payload",
    "parse_link",
    "resolve",
]
