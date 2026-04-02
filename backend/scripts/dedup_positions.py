"""
Elimina posiciones IOL duplicadas activas, dejando solo la más reciente por ticker.
Ejecutar una vez para limpiar el estado actual:
    railway run python scripts/dedup_positions.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import SessionLocal
from app.models import Position

db = SessionLocal()

# Traer todas las posiciones IOL activas
active = (
    db.query(Position)
    .filter(Position.source == "IOL", Position.is_active == True)
    .order_by(Position.user_id, Position.ticker, Position.id.desc())
    .all()
)

seen = set()
deduped = 0
for pos in active:
    key = (pos.user_id, pos.ticker)
    if key in seen:
        pos.is_active = False
        deduped += 1
    else:
        seen.add(key)

db.commit()
print(f"Dedup completo: {deduped} posiciones duplicadas desactivadas.")
db.close()
