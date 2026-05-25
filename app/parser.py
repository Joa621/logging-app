"""
Parse decompressed IPv6/UDP/CoAP bytes and extract sensor_data_t values.

This is a direct Python translation of log_parsed_ipv6_udp_coap() from
sink-demo-app (coap-RX branch), src/logger_helper.c.

Packet layout (74 bytes for the standard project template):

    IPv6 header     40 B   version=6, next_header=17 (UDP), hop_limit=255
    UDP header       8 B   src_port, dst_port, length, checksum
    CoAP header      4 B   [0x50][0x02][mid_hi][mid_lo]  (NON POST, TKL=0)
    CoAP option      7 B   [0xB6][b"sensor"]  Uri-Path delta=11 len=6
    CoAP option      5 B   [0x04][b"data"]    Uri-Path delta=0  len=4
    CoAP marker      1 B   0xFF
    sensor payload   9 B   float temp (4 B LE) + float pH (4 B LE) + uint8 bat

sensor_data_t is defined with __attribute__((packed)) in sensor_service.h:
    typedef struct __attribute__((packed)) {
        float    temp;   // 4 bytes, little-endian IEEE 754
        float    pH;     // 4 bytes, little-endian IEEE 754
        uint8_t  bat;    // 1 byte
    } sensor_data_t;     // = 9 bytes total, no padding
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

IPV6_HDR_LEN = 40
UDP_HDR_LEN = 8
SENSOR_PAYLOAD_LEN = 9   # sizeof(sensor_data_t) with __attribute__((packed))


class ParseError(ValueError):
    """Raised when the packet cannot be parsed into a valid sensor reading."""


@dataclass
class SensorValues:
    temp: float
    ph: float
    bat: int


def parse_ipv6_udp_coap(data: bytes) -> SensorValues:
    """
    Parse a decompressed IPv6/UDP/CoAP packet and return sensor values.

    Raises ParseError on any structural mismatch.
    """
    # -------------------------------------------------------------------------
    # IPv6 header  (40 bytes)
    # -------------------------------------------------------------------------
    if len(data) < IPV6_HDR_LEN + UDP_HDR_LEN + 4:
        raise ParseError(
            f"packet too short: {len(data)} bytes "
            f"(need at least {IPV6_HDR_LEN + UDP_HDR_LEN + 4})"
        )

    version = (data[0] >> 4) & 0xF
    if version != 6:
        raise ParseError(f"not an IPv6 packet (version field = {version})")

    ipv6_payload_len: int = struct.unpack_from(">H", data, 4)[0]
    next_header: int = data[6]

    if next_header != 17:
        raise ParseError(
            f"IPv6 next_header is not UDP (got {next_header}, expected 17)"
        )

    if len(data) < IPV6_HDR_LEN + ipv6_payload_len:
        raise ParseError(
            f"truncated packet: IPv6 payload_len={ipv6_payload_len} "
            f"but only {len(data) - IPV6_HDR_LEN} bytes remain"
        )

    # -------------------------------------------------------------------------
    # UDP header  (8 bytes)
    # -------------------------------------------------------------------------
    udp = data[IPV6_HDR_LEN:]
    ulen: int = struct.unpack_from(">H", udp, 4)[0]

    if ulen < UDP_HDR_LEN:
        raise ParseError(f"UDP length field too small: {ulen}")

    if IPV6_HDR_LEN + ulen > len(data):
        raise ParseError(
            f"UDP length {ulen} exceeds remaining packet bytes"
        )

    # -------------------------------------------------------------------------
    # CoAP  (starts at udp[8])
    # -------------------------------------------------------------------------
    coap = udp[UDP_HDR_LEN:]
    coap_len: int = ulen - UDP_HDR_LEN

    if coap_len < 4:
        raise ParseError(f"CoAP section too short: {coap_len} bytes")

    ver_type_tkl = coap[0]
    ver  = (ver_type_tkl >> 6) & 0x3
    typ  = (ver_type_tkl >> 4) & 0x3
    tkl  = ver_type_tkl & 0xF

    if ver != 1 or typ != 1 or tkl != 0:
        raise ParseError(
            f"CoAP header mismatch: expected ver=1 type=1(NON) tkl=0, "
            f"got ver={ver} type={typ} tkl={tkl}"
        )

    # -------------------------------------------------------------------------
    # Walk CoAP options until 0xFF payload marker
    # -------------------------------------------------------------------------
    idx = 4          # skip the 4-byte fixed CoAP header
    opt_num = 0
    saw_sensor = False
    saw_data = False

    while idx < coap_len:
        if coap[idx] == 0xFF:
            idx += 1   # step past the marker
            break

        opt_byte = coap[idx]
        idx += 1
        delta  = (opt_byte >> 4) & 0xF
        length = opt_byte & 0xF

        # Extended delta/length encoding (13, 14, 15) is not used in this project.
        if delta >= 13 or length >= 13:
            raise ParseError(
                f"CoAP option uses extended delta/len encoding "
                f"(delta={delta} len={length}) — not expected in this project"
            )

        opt_num += delta

        if idx + length > coap_len:
            raise ParseError("CoAP option value extends beyond packet boundary")

        if opt_num == 11:   # Uri-Path
            val = coap[idx : idx + length]
            if val == b"sensor":
                saw_sensor = True
            elif val == b"data":
                saw_data = True

        idx += length
    else:
        raise ParseError("CoAP payload marker (0xFF) not found")

    if not saw_sensor or not saw_data:
        raise ParseError(
            f"CoAP Uri-Path options mismatch "
            f"(saw_sensor={saw_sensor} saw_data={saw_data}); "
            f"expected both 'sensor' and 'data'"
        )

    # -------------------------------------------------------------------------
    # Sensor payload  (9 bytes: float temp + float pH + uint8 bat, all LE)
    # -------------------------------------------------------------------------
    payload = coap[idx:coap_len]
    if len(payload) != SENSOR_PAYLOAD_LEN:
        raise ParseError(
            f"sensor payload size {len(payload)} != {SENSOR_PAYLOAD_LEN} "
            f"(expected packed sensor_data_t: 4B float + 4B float + 1B uint8)"
        )

    temp, ph, bat = struct.unpack_from("<ffB", payload)
    return SensorValues(temp=temp, ph=ph, bat=bat)
