"""
Shared packet-construction helpers for tests.

Builds the same IPv6/UDP/CoAP structure as the real project:

    IPv6 (40 B) + UDP (8 B) + CoAP header (4 B)
    + Uri-Path "sensor" (7 B) + Uri-Path "data" (5 B)
    + 0xFF marker (1 B) + sensor payload (9 B)
    = 74 bytes total

sensor_data_t layout (packed, little-endian):
    float temp  (4 B LE IEEE 754)
    float pH    (4 B LE IEEE 754)
    uint8 bat   (1 B)
"""
from __future__ import annotations

import base64
import struct


# ---------------------------------------------------------------------------
# Low-level builders (mirrors schc-endpoint/tests/conftest.py exactly)
# ---------------------------------------------------------------------------

def build_sensor_bytes(temp: float, pH: float, bat: int) -> bytes:
    """9-byte packed sensor_data_t: float LE + float LE + uint8."""
    return struct.pack("<ffB", temp, pH, bat)


def build_coap_frame(sensor_payload: bytes) -> bytes:
    """
    CoAP NON POST frame with Uri-Path "sensor"/"data" and the given payload.

    Header:
      0x50  → VER=1, TYPE=NON(1), TKL=0
      0x02  → POST
      0x30, 0x31  → message ID = 0x3031

    Options (no token):
      0xB6 + b"sensor"  → delta=11 (Uri-Path), len=6
      0x04 + b"data"    → delta=0,  len=4

    0xFF payload marker followed by sensor_payload.
    """
    frame  = bytes([0x50, 0x02, 0x30, 0x31])
    frame += bytes([0xB6]) + b"sensor"
    frame += bytes([0x04]) + b"data"
    frame += bytes([0xFF])
    frame += sensor_payload
    return frame


def build_ipv6_udp_coap(
    temp: float = 25.0,
    pH: float = 7.5,
    bat: int = 80,
) -> bytes:
    """
    Complete 74-byte IPv6/UDP/CoAP packet with a packed 9-byte sensor payload.

    Addresses match the project template:
      src  2001:db8:0:1::1  (sensor node)
      dst  2001:db8:0:2::2  (sink / gateway)
    UDP checksum is left as 0x0000 (not validated by the parser).
    """
    coap    = build_coap_frame(build_sensor_bytes(temp, pH, bat))
    udp_len = 8 + len(coap)

    src_ip = bytes([
        0x20, 0x01, 0x0d, 0xb8, 0x00, 0x00, 0x00, 0x01,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01,
    ])
    dst_ip = bytes([
        0x20, 0x01, 0x0d, 0xb8, 0x00, 0x00, 0x00, 0x02,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x02,
    ])

    ipv6  = bytes([0x60, 0x00, 0x00, 0x00])       # ver=6, TC=0, flow=0
    ipv6 += struct.pack(">H", udp_len)             # IPv6 payload length
    ipv6 += bytes([0x11, 0xFF])                    # next_header=UDP, hop_limit=255
    ipv6 += src_ip + dst_ip

    udp   = struct.pack(">HH", 0x1234, 0x5678)    # src_port, dst_port
    udp  += struct.pack(">HH", udp_len, 0)        # length, checksum=0

    return ipv6 + udp + coap


def b64_packet(**kwargs) -> str:
    """Base64-encoded IPv6/UDP/CoAP packet (as forwarded by schc-endpoint)."""
    return base64.b64encode(build_ipv6_udp_coap(**kwargs)).decode()
