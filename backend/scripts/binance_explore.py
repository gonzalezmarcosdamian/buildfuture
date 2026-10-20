"""
Fase 0 — PoC Binance: validar auth + raw response de balances spot.
NO va a producción. Solo para exploración y documentación del DOR.

Las claves salen de backend/.env (BINANCE_API_KEY, BINANCE_API_SECRET), no del código.
"""
import hmac
import hashlib
import os
import sys
import time
import json
import urllib.parse
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

API_KEY = os.getenv("BINANCE_API_KEY")
SECRET = os.getenv("BINANCE_API_SECRET")
BASE = "https://api.binance.com"

if not API_KEY or not SECRET:
    sys.exit("Faltan BINANCE_API_KEY y BINANCE_API_SECRET en backend/.env")


def signed_get(endpoint: str, params: dict = {}) -> dict:
    p = {**params, "timestamp": int(time.time() * 1000)}
    query = urllib.parse.urlencode(p)
    sig = hmac.new(SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    r = httpx.get(
        f"{BASE}{endpoint}",
        params={**p, "signature": sig},
        headers={"X-MBX-APIKEY": API_KEY},
        timeout=10,
    )
    print(f"  HTTP {r.status_code} — {endpoint}")
    r.raise_for_status()
    return r.json()


def main():
    print("=== Binance PoC ===\n")

    # 1. Ping
    r = httpx.get(f"{BASE}/api/v3/ping", timeout=5)
    print(f"1. Ping: {'OK' if r.status_code == 200 else 'FAIL'}\n")

    # 2. Account info (balances)
    print("2. GET /api/v3/account (balances spot):")
    account = signed_get("/api/v3/account")

    balances = [b for b in account.get("balances", []) if float(b["free"]) + float(b["locked"]) > 0]
    print(f"   Assets con saldo > 0: {len(balances)}")
    for b in balances:
        qty = float(b["free"]) + float(b["locked"])
        print(f"   {b['asset']:10} free={b['free']:>16}  locked={b['locked']:>16}  total={qty:.8f}")

    # 3. Precios para los assets con saldo
    print("\n3. GET /api/v3/ticker/price (precios USDT):")
    tickers_raw = httpx.get(f"{BASE}/api/v3/ticker/price", timeout=10).json()
    price_map = {t["symbol"]: float(t["price"]) for t in tickers_raw}

    stablecoins = {"USDT", "USDC", "BUSD", "DAI", "TUSD", "FDUSD"}
    total_usd = 0.0
    for b in balances:
        asset = b["asset"]
        qty = float(b["free"]) + float(b["locked"])
        if asset in stablecoins:
            price = 1.0
        else:
            price = price_map.get(f"{asset}USDT") or price_map.get(f"{asset}BTC", 0)
        value = qty * price
        total_usd += value
        print(f"   {asset:10} qty={qty:.8f}  price_usdt={price:.4f}  value_usd={value:.2f}")

    print(f"\n   TOTAL estimado: ${total_usd:.2f} USD")

    # 4. Guardar raw para documentación
    raw = {
        "account_keys": list(account.keys()),
        "permissions": account.get("permissions", []),
        "accountType": account.get("accountType"),
        "balances_with_funds": balances,
        "total_usd_estimated": round(total_usd, 2),
    }
    out_path = "docs/integraciones/binance/raw_response.json"
    with open(out_path, "w") as f:
        json.dump(raw, f, indent=2)
    print(f"\n4. Raw guardado en {out_path}")
    print("\n=== PoC completado ===")


if __name__ == "__main__":
    main()
