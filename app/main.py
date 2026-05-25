"""
Logging application entry point.

Creates the FastAPI application, attaches the record store to app.state,
and includes all route handlers.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI

from .config import RECORDS_FILE
from .routes import router
from .storage import RecordStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)

app = FastAPI(
    title="Underwater Sensor Logging App",
    description=(
        "Receives decompressed IPv6/UDP/CoAP frames from the SCHC endpoint, "
        "extracts sensor_data_t values, and stores them as JSONL records."
    ),
    version="1.0.0",
)

# Attach a single store instance; routes access it via request.app.state.store
app.state.store = RecordStore(RECORDS_FILE)

app.include_router(router)
