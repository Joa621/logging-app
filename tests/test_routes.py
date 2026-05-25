"""
Unit tests for the HTTP routes.

Uses FastAPI's TestClient.  The real store is replaced with an in-memory stub
so tests do not write to disk and do not interfere with each other.
"""
from __future__ import annotations

import base64
from typing import List, Optional
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import SensorRecord

from .conftest import b64_packet, build_ipv6_udp_coap


# ---------------------------------------------------------------------------
# In-memory store stub
# ---------------------------------------------------------------------------

class _MemoryStore:
    """Minimal in-memory replacement for RecordStore used in tests."""

    def __init__(self) -> None:
        self._records: List[SensorRecord] = []

    def append(self, record: SensorRecord) -> None:
        self._records.append(record)

    def read_all(self) -> List[SensorRecord]:
        return list(self._records)

    def read_latest(self) -> Optional[SensorRecord]:
        return self._records[-1] if self._records else None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    mem_store = _MemoryStore()
    app.state.store = mem_store
    yield TestClient(app)
    # Restore a fresh store after each test
    app.state.store = _MemoryStore()


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

class TestHealth:

    def test_health_ok(self, client: TestClient) -> None:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# POST /sensor — happy path
# ---------------------------------------------------------------------------

class TestPostSensorValid:

    def test_returns_200_with_record(self, client: TestClient) -> None:
        body = {
            "data":    b64_packet(temp=25.0, pH=7.5, bat=80),
            "devEui":  "0102030405060708",
            "fCnt":    42,
            "time":    "2024-06-01T12:00:00.000Z",
        }
        r = client.post("/sensor", json=body)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        record = data["record"]
        assert abs(record["temp"] - 25.0) < 1e-4
        assert abs(record["ph"]   - 7.5)  < 1e-4
        assert record["bat"]     == 80
        assert record["dev_eui"] == "0102030405060708"
        assert record["f_cnt"]   == 42
        assert record["packet_time"] == "2024-06-01T12:00:00.000Z"

    def test_record_has_id_and_received_at(self, client: TestClient) -> None:
        r = client.post("/sensor", json={"data": b64_packet()})
        assert r.status_code == 200
        record = r.json()["record"]
        assert record["id"]
        assert record["received_at"]

    def test_optional_fields_nullable(self, client: TestClient) -> None:
        """devEui, fCnt, time are all optional."""
        r = client.post("/sensor", json={"data": b64_packet()})
        assert r.status_code == 200
        record = r.json()["record"]
        assert record["dev_eui"] is None
        assert record["f_cnt"] is None
        assert record["packet_time"] is None

    def test_different_sensor_values(self, client: TestClient) -> None:
        r = client.post("/sensor", json={"data": b64_packet(temp=12.5, pH=8.1, bat=42)})
        assert r.status_code == 200
        record = r.json()["record"]
        assert abs(record["temp"] - 12.5) < 1e-4
        assert abs(record["ph"]   - 8.1)  < 1e-4
        assert record["bat"] == 42

    def test_record_persisted_in_store(self, client: TestClient) -> None:
        client.post("/sensor", json={"data": b64_packet(temp=5.0, pH=6.0, bat=10)})
        r = client.get("/records")
        assert r.status_code == 200
        records = r.json()["records"]
        assert len(records) == 1
        assert abs(records[0]["temp"] - 5.0) < 1e-4


# ---------------------------------------------------------------------------
# POST /sensor — error paths
# ---------------------------------------------------------------------------

class TestPostSensorErrors:

    def test_invalid_json_body(self, client: TestClient) -> None:
        r = client.post(
            "/sensor",
            content=b"not json at all",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 400
        assert "invalid JSON" in r.json()["error"]

    def test_missing_data_field(self, client: TestClient) -> None:
        r = client.post("/sensor", json={"devEui": "abc"})
        assert r.status_code == 422

    def test_empty_data_field(self, client: TestClient) -> None:
        r = client.post("/sensor", json={"data": ""})
        assert r.status_code == 422

    def test_invalid_base64(self, client: TestClient) -> None:
        r = client.post("/sensor", json={"data": "!!!not-base64!!!"})
        assert r.status_code == 422
        assert "base64" in r.json()["error"]

    def test_malformed_packet_too_short(self, client: TestClient) -> None:
        b64 = base64.b64encode(b"\x60\x00\x00\x00\x00\x08\x11\xff" + bytes(32)).decode()
        r = client.post("/sensor", json={"data": b64})
        assert r.status_code == 422
        assert "parse" in r.json()["error"].lower()

    def test_wrong_ipv6_version(self, client: TestClient) -> None:
        """Feed an IPv4-looking packet."""
        raw = bytearray(build_ipv6_udp_coap())
        raw[0] = 0x45   # IPv4 version
        b64 = base64.b64encode(bytes(raw)).decode()
        r = client.post("/sensor", json={"data": b64})
        assert r.status_code == 422

    def test_storage_failure_returns_500(self, client: TestClient) -> None:
        broken_store = MagicMock()
        broken_store.append.side_effect = OSError("disk full")
        app.state.store = broken_store
        r = client.post("/sensor", json={"data": b64_packet()})
        assert r.status_code == 500
        assert "storage" in r.json()["error"]


# ---------------------------------------------------------------------------
# GET /records
# ---------------------------------------------------------------------------

class TestGetRecords:

    def test_empty_store(self, client: TestClient) -> None:
        r = client.get("/records")
        assert r.status_code == 200
        assert r.json() == {"records": []}

    def test_returns_all_inserted(self, client: TestClient) -> None:
        for temp in [10.0, 20.0, 30.0]:
            client.post("/sensor", json={"data": b64_packet(temp=temp)})
        r = client.get("/records")
        records = r.json()["records"]
        assert len(records) == 3
        temps = [rec["temp"] for rec in records]
        for expected, actual in zip([10.0, 20.0, 30.0], temps):
            assert abs(actual - expected) < 1e-4


# ---------------------------------------------------------------------------
# GET /records/latest
# ---------------------------------------------------------------------------

class TestGetLatest:

    def test_no_records_returns_404(self, client: TestClient) -> None:
        r = client.get("/records/latest")
        assert r.status_code == 404

    def test_returns_last_inserted(self, client: TestClient) -> None:
        client.post("/sensor", json={"data": b64_packet(temp=1.0)})
        client.post("/sensor", json={"data": b64_packet(temp=2.0)})
        client.post("/sensor", json={"data": b64_packet(temp=3.0)})
        r = client.get("/records/latest")
        assert r.status_code == 200
        assert abs(r.json()["record"]["temp"] - 3.0) < 1e-4
