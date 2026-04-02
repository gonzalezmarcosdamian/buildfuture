## BuildFuture — comandos de desarrollo local
## Requiere: Python 3.11+, Node 18+

BACKEND_DIR := backend
DB_FILE     := $(BACKEND_DIR)/buildfuture.db

# ── Backend ────────────────────────────────────────────────────────────────────

# Arranca backend en modo mock completo (5 personas de QA precargadas)
dev-mock:
	cd $(BACKEND_DIR) && MOCK_SEED=true MOCK_INTEGRATIONS=true \
	uvicorn app.main:app --reload --port 8000

# Arranca backend normal (solo usuario marcos del seed original)
dev:
	cd $(BACKEND_DIR) && uvicorn app.main:app --reload --port 8000

# Borra DB local y la recrea con los 5 usuarios de QA
mock-reset:
	@echo "Borrando DB local..."
	rm -f $(DB_FILE)
	@echo "Iniciando backend para seedear..."
	cd $(BACKEND_DIR) && MOCK_SEED=true MOCK_INTEGRATIONS=true python -c "\
from app.database import engine, SessionLocal; \
from app.models import Base; \
Base.metadata.create_all(bind=engine); \
from app.seed import seed; \
from app.seed_mock import seed_mock; \
db = SessionLocal(); \
seed(db); \
seed_mock(db); \
db.close(); \
print('✓ DB lista con 5 usuarios de QA')"

# Muestra la URL de mock-login para un usuario específico
# Uso: make mock-user USER=matiasmoron
mock-user:
	@echo ""
	@echo "Abrí esta URL en el browser (frontend debe estar corriendo):"
	@echo "  http://localhost:3000/mock-login?user=$(USER)"
	@echo ""
	@echo "Usuarios disponibles: marcos | matiasmoron | nuevo | renta | capital | mixto"

# Ver estado de cada usuario mock en la DB
mock-status:
	cd $(BACKEND_DIR) && python -c "\
from app.database import SessionLocal; \
from app.models import Position, BudgetConfig, CapitalGoal, Integration; \
from app.seed_mock import USERS; \
db = SessionLocal(); \
print('\nUsuario         | Posiciones | Presupuesto | Metas | IOL'); \
print('-' * 65); \
for alias, uid in USERS.items(): \
    pos = db.query(Position).filter(Position.user_id == uid).count(); \
    bud = db.query(BudgetConfig).filter(BudgetConfig.user_id == uid).count(); \
    gol = db.query(CapitalGoal).filter(CapitalGoal.user_id == uid).count(); \
    iol = db.query(Integration).filter(Integration.user_id == uid, Integration.provider == 'IOL', Integration.is_connected == True).count(); \
    print(f'{alias:15} | {pos:10} | {bud:11} | {gol:5} | {\"✓\" if iol else \"—\"}'); \
db.close()"

# ── Frontend ───────────────────────────────────────────────────────────────────

# Arranca frontend en modo mock (apunta a backend local, sin Supabase auth)
frontend-mock:
	cd frontend && NEXT_PUBLIC_MOCK_AUTH=true \
	NEXT_PUBLIC_API_URL=http://localhost:8000 \
	npm run dev

# ── Combo ──────────────────────────────────────────────────────────────────────

# Reset completo + arranca backend + imprime instrucciones
qa-start:
	@$(MAKE) mock-reset
	@echo ""
	@echo "Ahora en otra terminal:"
	@echo "  make frontend-mock"
	@echo ""
	@echo "Y abrí en el browser:"
	@echo "  http://localhost:3000/mock-login?user=matiasmoron"
	@echo "  http://localhost:3000/mock-login?user=nuevo"
	@echo "  http://localhost:3000/mock-login?user=renta"
	@echo "  http://localhost:3000/mock-login?user=capital"
	@echo "  http://localhost:3000/mock-login?user=mixto"
	@$(MAKE) dev-mock
