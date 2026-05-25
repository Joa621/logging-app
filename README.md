# logging-app

Receives decompressed IPv6/UDP/CoAP frames from the SCHC endpoint application,
parses the sensor payload, and stores structured sensor records.

**The logging app does not do SCHC decompression.**
That is the responsibility of `schc-endpoint`.  This application only receives
already-decompressed bytes and extracts sensor values.

---

## Architecture position

```
schc-endpoint              [decompresses SCHC, forwards raw bytes]
  |  POST /sensor  JSON { "data": "<base64 IPv6/UDP/CoAP>",
  |                        "devEui": "...", "fCnt": N, "time": "..." }
  v
logging-app                [THIS PROJECT — parses packet, stores records]
  |  storage/records.jsonl
```

---

## Packet format parsed

The `data` field is base64 of a raw IPv6/UDP/CoAP packet:

```
IPv6 header     40 B   version=6, next_header=17 (UDP)
UDP header       8 B
CoAP header      4 B   NON POST, VER=1, TKL=0
CoAP option      7 B   Uri-Path "sensor"
CoAP option      5 B   Uri-Path "data"
0xFF marker      1 B
sensor payload   9 B   → float temp (LE) + float pH (LE) + uint8 bat
                       = 74 bytes total
```

The sensor payload corresponds to `sensor_data_t` defined in the project's
`sensor_service.h` with `__attribute__((packed))`:

```c
typedef struct __attribute__((packed)) {
    float    temp;   // 4 bytes, little-endian IEEE 754
    float    pH;     // 4 bytes, little-endian IEEE 754
    uint8_t  bat;    // 1 byte
} sensor_data_t;     // = 9 bytes, no padding
```

---

## Project layout

```
logging-app/
├── app/
│   ├── __init__.py
│   ├── config.py        # env-var settings
│   ├── models.py        # InboundPayload, SensorRecord
│   ├── parser.py        # IPv6/UDP/CoAP + sensor_data_t parsing
│   ├── storage.py       # thread-safe JSONL record store
│   ├── routes.py        # FastAPI route handlers
│   └── main.py          # FastAPI app + store wiring
├── storage/
│   └── records.jsonl    # created automatically on first write
├── tests/
│   ├── conftest.py      # packet-construction helpers
│   ├── sample_forwarded.json
│   ├── test_parser.py   # unit tests — parser only, no HTTP
│   └── test_routes.py   # unit tests — all HTTP routes
├── .env.example
├── requirements.txt
└── README.md
```

---

## Install

```bash
cd logging-app
pip install -r requirements.txt
```

---

## Configure

```bash
cp .env.example .env
# Edit .env if you need a different port or storage path.
```

---

## Run

```bash
cd logging-app
uvicorn app.main:app --host 0.0.0.0 --port 9090
```

Or with explicit env vars (no .env file needed):

```bash
BIND_HOST=0.0.0.0 BIND_PORT=9090 \
RECORDS_FILE=./storage/records.jsonl \
uvicorn app.main:app --host 0.0.0.0 --port 9090
```

The app exposes:

| Method | Route            | Description                               |
|--------|------------------|-------------------------------------------|
| POST   | `/sensor`        | Receive decompressed frame, parse, store  |
| GET    | `/health`        | Liveness check                            |
| GET    | `/records`       | Return all stored records                 |
| GET    | `/records/latest`| Return the most recent record             |

---

## Test with curl

### POST /sensor using the sample forwarded body

```bash
curl -s -X POST http://localhost:9090/sensor \
  -H "Content-Type: application/json" \
  -d @tests/sample_forwarded.json \
  | python3 -m json.tool
```

Expected response:

```json
{
  "status": "ok",
  "record": {
    "id": "<uuid>",
    "received_at": "2024-06-01T12:00:00.123456+00:00",
    "dev_eui": "0102030405060708",
    "f_cnt": 42,
    "packet_time": "2024-06-01T12:00:00.000Z",
    "temp": 25.0,
    "ph": 7.5,
    "bat": 80
  }
}
```

### Retrieve all records

```bash
curl -s http://localhost:9090/records | python3 -m json.tool
```

### Retrieve latest record

```bash
curl -s http://localhost:9090/records/latest | python3 -m json.tool
```

---

## Example stored record (records.jsonl)

Each line in `storage/records.jsonl` is a JSON object:

```json
{"id":"a1b2c3d4-e5f6-7890-abcd-ef1234567890","received_at":"2024-06-01T12:00:00.123456+00:00","dev_eui":"0102030405060708","f_cnt":42,"packet_time":"2024-06-01T12:00:00.000Z","temp":25.0,"ph":7.5,"bat":80}
```

---

## Run tests

```bash
# All tests
pytest tests/ -v

# Parser unit tests only (no HTTP layer)
pytest tests/test_parser.py -v

# Route tests only
pytest tests/test_routes.py -v
```

---

## Connecting to schc-endpoint

In `schc-endpoint`, set:

```
LOGGING_APP_URL=http://<this-host>:9090/sensor
```

ChirpStack → schc-endpoint → **logging-app** is the full chain.
