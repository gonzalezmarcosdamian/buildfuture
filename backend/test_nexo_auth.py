import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from app.services.nexo_client import NexoClient

client = NexoClient(
    api_key=os.getenv("NEXO_API_KEY"),
    api_secret=os.getenv("NEXO_API_SECRET"),
)

print("=== Test auth ===")
try:
    client.test_auth()
    print("Auth OK")
except Exception as e:
    print(f"Auth FAIL: {e}")
    raise SystemExit(1)

print("\n=== Balances ===")
positions = client.get_balances()
if not positions:
    print("Sin balances (cuenta vacía)")
else:
    for p in positions:
        print(f"{p.ticker:8} {p.asset_type:8} balance={p.quantity} precio=${p.current_price_usd} yield={p.annual_yield_pct*100:.1f}%")
