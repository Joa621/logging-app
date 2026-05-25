"""
Pydantic models for the logging application.

InboundPayload   — the JSON body POSTed by the SCHC endpoint app.
SensorRecord     — a fully parsed record stored in JSONL and returned by the API.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class InboundPayload(BaseModel):
    """
    Body forwarded by schc-endpoint after SCHC decompression.

    Shape matches ForwardPayload in schc-endpoint/app/models.py:
        {
          "data":    "<base64-encoded decompressed IPv6/UDP/CoAP bytes>",
          "devEui":  "0102030405060708",
          "fCnt":    42,
          "time":    "2024-06-01T12:00:00.000Z"
        }
    """

    data: str                     # base64-encoded raw IPv6/UDP/CoAP bytes
    devEui: Optional[str] = None  # LoRaWAN device EUI (hex string)
    fCnt: Optional[int] = None    # LoRaWAN frame counter
    time: Optional[str] = None    # ISO-8601 timestamp from ChirpStack

    model_config = {"extra": "allow"}


class SensorRecord(BaseModel):
    """A fully parsed and stored sensor reading."""

    id: str                          # UUID assigned at ingestion
    received_at: str                 # UTC ISO-8601 timestamp of ingestion
    dev_eui: Optional[str] = None
    f_cnt: Optional[int] = None
    packet_time: Optional[str] = None  # time field forwarded from ChirpStack
    temp: float                      # temperature (°C), little-endian IEEE 754 float
    ph: float                        # pH value,        little-endian IEEE 754 float
    bat: int                         # battery level (0–255)
