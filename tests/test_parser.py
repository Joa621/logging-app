"""
Unit tests for app.parser — the IPv6/UDP/CoAP + sensor payload parser.

No HTTP layer; tests call parse_ipv6_udp_coap() directly.
"""
from __future__ import annotations

import struct

import pytest

from app.parser import ParseError, parse_ipv6_udp_coap

from .conftest import build_ipv6_udp_coap, build_sensor_bytes, build_coap_frame


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestValidPackets:

    def test_standard_values(self) -> None:
        pkt = build_ipv6_udp_coap(temp=25.0, pH=7.5, bat=80)
        sv = parse_ipv6_udp_coap(pkt)
        assert abs(sv.temp - 25.0) < 1e-5
        assert abs(sv.ph - 7.5) < 1e-5
        assert sv.bat == 80

    def test_different_values(self) -> None:
        pkt = build_ipv6_udp_coap(temp=12.5, pH=8.1, bat=42)
        sv = parse_ipv6_udp_coap(pkt)
        assert abs(sv.temp - 12.5) < 1e-5
        assert abs(sv.ph - 8.1) < 1e-5
        assert sv.bat == 42

    def test_boundary_battery_zero(self) -> None:
        pkt = build_ipv6_udp_coap(temp=0.0, pH=7.0, bat=0)
        sv = parse_ipv6_udp_coap(pkt)
        assert sv.bat == 0

    def test_boundary_battery_max(self) -> None:
        pkt = build_ipv6_udp_coap(temp=0.0, pH=7.0, bat=255)
        sv = parse_ipv6_udp_coap(pkt)
        assert sv.bat == 255

    def test_packet_is_74_bytes(self) -> None:
        """Standard project packet template is exactly 74 bytes."""
        pkt = build_ipv6_udp_coap()
        assert len(pkt) == 74

    def test_sensor_payload_roundtrip(self) -> None:
        """Encoding and parsing must be lossless for valid float values."""
        for temp, pH, bat in [(1.0, 2.0, 100), (-5.5, 14.0, 1), (99.9, 0.001, 200)]:
            pkt = build_ipv6_udp_coap(temp=temp, pH=pH, bat=bat)
            sv = parse_ipv6_udp_coap(pkt)
            # struct.pack/unpack round-trip for 32-bit float
            expected_temp = struct.unpack("<f", struct.pack("<f", temp))[0]
            expected_pH   = struct.unpack("<f", struct.pack("<f", pH))[0]
            assert abs(sv.temp - expected_temp) < 1e-6
            assert abs(sv.ph  - expected_pH)   < 1e-6
            assert sv.bat == bat


# ---------------------------------------------------------------------------
# IPv6 header errors
# ---------------------------------------------------------------------------

class TestIPv6Errors:

    def test_too_short(self) -> None:
        with pytest.raises(ParseError, match="too short"):
            parse_ipv6_udp_coap(b"\x60" * 10)

    def test_wrong_version(self) -> None:
        pkt = bytearray(build_ipv6_udp_coap())
        pkt[0] = 0x45   # IPv4
        with pytest.raises(ParseError, match="not an IPv6"):
            parse_ipv6_udp_coap(bytes(pkt))

    def test_next_header_not_udp(self) -> None:
        pkt = bytearray(build_ipv6_udp_coap())
        pkt[6] = 6   # TCP
        with pytest.raises(ParseError, match="not UDP"):
            parse_ipv6_udp_coap(bytes(pkt))


# ---------------------------------------------------------------------------
# CoAP errors
# ---------------------------------------------------------------------------

class TestCoAPErrors:

    def test_wrong_coap_version(self) -> None:
        """CoAP first byte: change ver bits (bits 7-6) from 01 to 00."""
        pkt = bytearray(build_ipv6_udp_coap())
        # CoAP starts at byte 48 (40 IPv6 + 8 UDP)
        pkt[48] = 0x10   # ver=0, type=1, tkl=0
        with pytest.raises(ParseError, match="CoAP header mismatch"):
            parse_ipv6_udp_coap(bytes(pkt))

    def test_wrong_coap_type(self) -> None:
        """Change CoAP type from NON(1) to CON(0)."""
        pkt = bytearray(build_ipv6_udp_coap())
        pkt[48] = 0x40   # ver=1, type=CON(0), tkl=0
        with pytest.raises(ParseError, match="CoAP header mismatch"):
            parse_ipv6_udp_coap(bytes(pkt))

    def test_missing_sensor_option(self) -> None:
        """Build a CoAP frame that lacks the 'sensor' Uri-Path option."""
        coap  = bytes([0x50, 0x02, 0x30, 0x31])
        coap += bytes([0x04]) + b"data"    # only 'data', no 'sensor'
        coap += bytes([0xFF])
        coap += build_sensor_bytes(25.0, 7.5, 80)
        udp_len = 8 + len(coap)
        src_ip  = bytes(16)
        dst_ip  = bytes(16)
        ipv6    = bytes([0x60, 0x00, 0x00, 0x00]) + struct.pack(">H", udp_len) + bytes([0x11, 0xFF]) + src_ip + dst_ip
        udp     = struct.pack(">HH", 0x1234, 0x5678) + struct.pack(">HH", udp_len, 0)
        pkt     = ipv6 + udp + coap
        with pytest.raises(ParseError, match="Uri-Path"):
            parse_ipv6_udp_coap(pkt)

    def test_no_payload_marker(self) -> None:
        """CoAP frame with options but no 0xFF marker."""
        coap = bytes([0x50, 0x02, 0x30, 0x31])
        # Options present but no 0xFF — the while loop exhausts coap_len
        coap += bytes([0xB6]) + b"sensor"
        coap += bytes([0x04]) + b"data"
        # deliberately omit 0xFF and sensor payload
        udp_len = 8 + len(coap)
        src_ip  = bytes(16)
        dst_ip  = bytes(16)
        ipv6 = bytes([0x60, 0x00, 0x00, 0x00]) + struct.pack(">H", udp_len) + bytes([0x11, 0xFF]) + src_ip + dst_ip
        udp  = struct.pack(">HH", 0x1234, 0x5678) + struct.pack(">HH", udp_len, 0)
        with pytest.raises(ParseError, match="payload marker"):
            parse_ipv6_udp_coap(ipv6 + udp + coap)


# ---------------------------------------------------------------------------
# Sensor payload size errors
# ---------------------------------------------------------------------------

class TestSensorPayloadErrors:

    def test_payload_too_short(self) -> None:
        """Only 8 bytes after the 0xFF marker instead of 9."""
        coap  = bytes([0x50, 0x02, 0x30, 0x31])
        coap += bytes([0xB6]) + b"sensor"
        coap += bytes([0x04]) + b"data"
        coap += bytes([0xFF])
        coap += b"\x00" * 8   # 8 bytes instead of 9
        udp_len = 8 + len(coap)
        src_ip  = bytes(16)
        dst_ip  = bytes(16)
        ipv6 = bytes([0x60, 0x00, 0x00, 0x00]) + struct.pack(">H", udp_len) + bytes([0x11, 0xFF]) + src_ip + dst_ip
        udp  = struct.pack(">HH", 0x1234, 0x5678) + struct.pack(">HH", udp_len, 0)
        with pytest.raises(ParseError, match="sensor payload size"):
            parse_ipv6_udp_coap(ipv6 + udp + coap)

    def test_payload_too_long(self) -> None:
        """10 bytes after the 0xFF marker instead of 9."""
        coap  = bytes([0x50, 0x02, 0x30, 0x31])
        coap += bytes([0xB6]) + b"sensor"
        coap += bytes([0x04]) + b"data"
        coap += bytes([0xFF])
        coap += b"\x00" * 10
        udp_len = 8 + len(coap)
        src_ip  = bytes(16)
        dst_ip  = bytes(16)
        ipv6 = bytes([0x60, 0x00, 0x00, 0x00]) + struct.pack(">H", udp_len) + bytes([0x11, 0xFF]) + src_ip + dst_ip
        udp  = struct.pack(">HH", 0x1234, 0x5678) + struct.pack(">HH", udp_len, 0)
        with pytest.raises(ParseError, match="sensor payload size"):
            parse_ipv6_udp_coap(ipv6 + udp + coap)
