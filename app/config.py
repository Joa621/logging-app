"""
Runtime configuration loaded from environment variables (or .env file).

BIND_HOST      Address FastAPI listens on          (default 0.0.0.0)
BIND_PORT      Port FastAPI listens on             (default 9090)
RECORDS_FILE   Path to the JSONL storage file      (default ./storage/records.jsonl)
"""
import os

from dotenv import load_dotenv

load_dotenv()

BIND_HOST: str = os.getenv("BIND_HOST", "0.0.0.0")
BIND_PORT: int = int(os.getenv("BIND_PORT", "9090"))
RECORDS_FILE: str = os.getenv("RECORDS_FILE", "./storage/records.jsonl")
