"""
Script de diagnóstico IOL — corre directo sin la app.
Uso: python test_iol_auth.py
Requiere: backend/.env con IOL_USERNAME y IOL_PASSWORD
"""
import os
import httpx
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

username = os.getenv("IOL_USERNAME")
password = os.getenv("IOL_PASSWORD")

if not username or not password:
    print("ERROR: falta IOL_USERNAME o IOL_PASSWORD en backend/.env")
    raise SystemExit(1)

print(f"Usuario: {username}")
print(f"Password: {'*' * len(password)}")
print()

IOL_BASE = "https://api.invertironline.com"

# --- Intento 1: form-encoded como string ---
print("=== Intento 1: content como string ===")
payload_str = f"username={username}&password={password}&grant_type=password"
resp = httpx.post(
    f"{IOL_BASE}/token",
    content=payload_str,
    headers={"Content-Type": "application/x-www-form-urlencoded"},
    timeout=20,
)
print(f"Status: {resp.status_code}")
print(f"Response headers: {dict(resp.headers)}")
print(f"Body: {resp.text[:500]}")
print()

if resp.status_code == 200:
    token = resp.json().get("access_token", "")
    print(f"TOKEN OBTENIDO: {token[:40]}...")
    print()
    print("=== Probando portafolio ===")
    r2 = httpx.get(
        f"{IOL_BASE}/api/v2/portafolio/argentina",
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    print(f"Portafolio status: {r2.status_code}")
    print(f"Portafolio body preview: {r2.text[:300]}")
else:
    # --- Intento 2: data dict (httpx urlencode automático) ---
    print("=== Intento 2: data dict ===")
    resp2 = httpx.post(
        f"{IOL_BASE}/token",
        data={"username": username, "password": password, "grant_type": "password"},
        timeout=20,
    )
    print(f"Status: {resp2.status_code}")
    print(f"Body: {resp2.text[:500]}")
