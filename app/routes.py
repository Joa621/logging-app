"""
FastAPI route handlers for the logging application.

Routes:
    POST /sensor          Receive a forwarded frame from schc-endpoint,
                          parse it, store the record, return parsed values.
    GET  /health          Liveness check.
    GET  /records         Return all stored records.
    GET  /records/latest  Return the most recent record.
"""
from __future__ import annotations

import base64
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from .models import InboundPayload, SensorRecord
from .parser import ParseError, parse_ipv6_udp_coap

logger = logging.getLogger(__name__)
router = APIRouter()

_UI_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Sensor Log</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: sans-serif; font-size: 14px; color: #111; background: #fff; padding: 28px 32px; }
    h1 { font-size: 17px; font-weight: 600; margin-bottom: 24px; }

    .latest-wrap { margin-bottom: 28px; padding-bottom: 24px; border-bottom: 1px solid #ddd; }
    .latest-meta { font-size: 12px; color: #777; margin-bottom: 12px; }
    .readings { display: flex; gap: 40px; }
    .reading .label { font-size: 11px; color: #888; text-transform: uppercase; letter-spacing: .05em; margin-bottom: 3px; }
    .reading .value { font-family: monospace; font-size: 26px; font-weight: 600; }
    .reading .unit  { font-size: 13px; color: #666; margin-left: 3px; }

    .bar { display: flex; align-items: center; gap: 10px; margin-top: 4px; }
    .bar-track { width: 80px; height: 6px; background: #e0e0e0; border-radius: 3px; overflow: hidden; }
    .bar-fill  { height: 100%; background: #555; border-radius: 3px; }

    .table-header { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
    .table-header h2 { font-size: 14px; font-weight: 600; }
    button { font-size: 12px; padding: 3px 10px; cursor: pointer; border: 1px solid #bbb; background: #fff; border-radius: 3px; }
    button:hover { background: #f4f4f4; }
    .ts { font-size: 12px; color: #999; margin-left: auto; }

    table { width: 100%; border-collapse: collapse; }
    th { text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: #777;
         padding: 6px 10px; border-bottom: 2px solid #ddd; white-space: nowrap; }
    td { padding: 7px 10px; font-family: monospace; font-size: 13px; border-bottom: 1px solid #eee; }
    tr:last-child td { border-bottom: none; }
    tbody tr:hover td { background: #fafafa; }
    .muted { color: #aaa; }
    .no-data { color: #aaa; font-style: italic; padding: 14px 10px; font-family: sans-serif; }
  </style>
</head>
<body>
  <h1>Sensor Log</h1>

  <div id="latest" class="latest-wrap"><p class="muted">Loading&hellip;</p></div>

  <div class="table-header">
    <h2>Records</h2>
    <button onclick="refresh()">Refresh</button>
    <span class="ts" id="ts"></span>
  </div>
  <table>
    <thead>
      <tr>
        <th>Received</th>
        <th>Device EUI</th>
        <th>fCnt</th>
        <th>Temp &deg;C</th>
        <th>pH</th>
        <th>Bat</th>
        <th>ID</th>
      </tr>
    </thead>
    <tbody id="tbody"><tr><td colspan="7" class="no-data">Loading&hellip;</td></tr></tbody>
  </table>

  <script>
    function fmt(iso) {
      if (!iso) return '—';
      return new Date(iso).toLocaleString();
    }

    async function loadLatest() {
      const box = document.getElementById('latest');
      try {
        const res = await fetch('/records/latest');
        if (res.status === 404) {
          box.innerHTML = '<p class="muted">No records yet.</p>';
          return;
        }
        const { record: r } = await res.json();
        const pct = Math.round(r.bat / 255 * 100);
        box.innerHTML = `
          <div class="latest-meta">Latest &mdash; ${fmt(r.received_at)}</div>
          <div class="readings">
            <div class="reading">
              <div class="label">Temperature</div>
              <div class="value">${r.temp.toFixed(3)}<span class="unit">&deg;C</span></div>
            </div>
            <div class="reading">
              <div class="label">pH</div>
              <div class="value">${r.ph.toFixed(3)}</div>
            </div>
            <div class="reading">
              <div class="label">Battery</div>
              <div class="value">${pct}<span class="unit">%</span></div>
              <div class="bar">
                <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
              </div>
            </div>
          </div>`;
      } catch {
        box.innerHTML = '<p class="muted">Could not load latest record.</p>';
      }
    }

    async function loadRecords() {
      const tbody = document.getElementById('tbody');
      try {
        const { records } = await (await fetch('/records')).json();
        if (!records.length) {
          tbody.innerHTML = '<tr><td colspan="7" class="no-data">No records yet.</td></tr>';
          return;
        }
        tbody.innerHTML = [...records].reverse().map(r => `
          <tr>
            <td>${fmt(r.received_at)}</td>
            <td>${r.dev_eui || '<span class=muted>—</span>'}</td>
            <td>${r.f_cnt != null ? r.f_cnt : '<span class=muted>—</span>'}</td>
            <td>${r.temp.toFixed(3)}</td>
            <td>${r.ph.toFixed(3)}</td>
            <td>${r.bat}</td>
            <td title="${r.id}" style="color:#aaa">${r.id.slice(0,8)}&hellip;</td>
          </tr>`).join('');
      } catch {
        tbody.innerHTML = '<tr><td colspan="7" class="no-data">Could not load records.</td></tr>';
      }
    }

    async function refresh() {
      await Promise.all([loadLatest(), loadRecords()]);
      document.getElementById('ts').textContent = 'Updated ' + new Date().toLocaleTimeString();
    }

    refresh();
    setInterval(refresh, 10000);
  </script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# GET /  — browser UI
# ---------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def ui():
    return _UI_HTML


# ---------------------------------------------------------------------------
# Dependency: store is injected via app.state so tests can override it easily.
# ---------------------------------------------------------------------------

def _get_store(request: Request):
    return request.app.state.store


# ---------------------------------------------------------------------------
# POST /sensor
# ---------------------------------------------------------------------------

@router.post("/sensor")
async def receive_sensor(request: Request):
    """
    Accept a decompressed frame from the SCHC endpoint app.

    Expected body:
        {
          "data":    "<base64 of decompressed IPv6/UDP/CoAP bytes>",
          "devEui":  "0102030405060708",
          "fCnt":    42,
          "time":    "2024-06-01T12:00:00.000Z"
        }

    Returns:
        200  {"status": "ok", "record": {...}}
        400  {"error": "invalid JSON"}
        422  {"error": "<validation / parse reason>"}
        500  {"error": "storage write failed"}
    """
    # 1. Parse JSON body
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "invalid JSON"})

    # 2. Validate shape
    try:
        payload = InboundPayload.model_validate(body)
    except Exception as exc:
        return JSONResponse(
            status_code=422,
            content={"error": f"request validation error: {exc}"},
        )

    if not payload.data:
        return JSONResponse(
            status_code=422, content={"error": "missing or empty 'data' field"}
        )

    # 3. Decode base64
    try:
        raw_bytes = base64.b64decode(payload.data, validate=True)
    except Exception:
        return JSONResponse(
            status_code=422,
            content={"error": "invalid base64 in 'data' field"},
        )

    # 4. Parse IPv6/UDP/CoAP → sensor values
    try:
        sensor = parse_ipv6_udp_coap(raw_bytes)
    except ParseError as exc:
        logger.warning(
            "Packet parse error  devEui=%s fCnt=%s  reason: %s",
            payload.devEui, payload.fCnt, exc,
        )
        return JSONResponse(
            status_code=422,
            content={"error": f"packet parse error: {exc}"},
        )

    # 5. Build record
    record = SensorRecord(
        id=str(uuid.uuid4()),
        received_at=datetime.now(timezone.utc).isoformat(),
        dev_eui=payload.devEui,
        f_cnt=payload.fCnt,
        packet_time=payload.time,
        temp=round(sensor.temp, 6),
        ph=round(sensor.ph, 6),
        bat=sensor.bat,
    )

    # 6. Persist
    store = _get_store(request)
    try:
        store.append(record)
    except Exception as exc:
        logger.error("Storage write failed: %s", exc)
        return JSONResponse(
            status_code=500, content={"error": "storage write failed"}
        )

    logger.info(
        "Stored  id=%s  devEui=%s  fCnt=%s  temp=%.3f  pH=%.3f  bat=%d",
        record.id, record.dev_eui, record.f_cnt,
        record.temp, record.ph, record.bat,
    )

    return {"status": "ok", "record": record.model_dump()}


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

@router.get("/health")
async def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# GET /records
# ---------------------------------------------------------------------------

@router.get("/records")
async def get_records(request: Request):
    store = _get_store(request)
    return {"records": [r.model_dump() for r in store.read_all()]}


# ---------------------------------------------------------------------------
# GET /records/latest
# ---------------------------------------------------------------------------

@router.get("/records/latest")
async def get_latest(request: Request):
    store = _get_store(request)
    record = store.read_latest()
    if record is None:
        return JSONResponse(
            status_code=404, content={"error": "no records stored yet"}
        )
    return {"record": record.model_dump()}
