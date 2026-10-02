# NexoEventos

Base local del proyecto universitario de Cloud Computing para una plataforma ficticia de eventos, reservas y entradas QR.

## Estado

- Frontend: React + TypeScript + Vite.
- Backend: FastAPI con autenticación, autorización por rol, catálogo, reservas simuladas, entradas QR y validación de ingreso.
- Persistencia: PostgreSQL 14 local con migraciones Alembic y datos ficticios reproducibles.
- Infraestructura: Terraform AWS V1 preparado y validado localmente; Azure y GCP permanecen como referencias sin recursos.
- Cloud: no se ha creado, modificado ni eliminado ningún recurso.

## Inicio rápido

### Backend

```bash
cd backend
source .venv/bin/activate
alembic upgrade head
../scripts/dev-bootstrap.py
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
PATH="/opt/homebrew/opt/node@24/bin:$PATH" npm run dev
```

Abre `http://localhost:5173`. El frontend consulta el backend en `http://localhost:8000` por defecto.

La versión del proyecto está fijada en Node.js 24.21.0 mediante `.nvmrc`, `.node-version`, `engines` y la configuración del terminal de VS Code. No se desinstaló Node 26.

## PostgreSQL local

- Base de desarrollo: `nexoeventos`.
- Base aislada de pruebas: `nexoeventos_test`.
- Propietario sin inicio de sesión: `nexoeventos_owner`.
- Usuario limitado de aplicación: `nexoeventos_app`.
- Conexión local mediante socket Unix y autenticación local existente; no se almacena contraseña.

El usuario de aplicación no puede crear tablas, insertar eventos ni eliminar reservas. Las migraciones se ejecutan separadamente con el usuario administrador local:

```bash
./scripts/db-migrate.sh
```

Antes del primer inicio, `scripts/dev-bootstrap.py` genera la clave local de cifrado en `backend/.env` y solicita contraseñas temporales para cuentas ficticias de organizador y operador. No hay contraseñas predeterminadas en el código. El registro público crea exclusivamente clientes.

Endpoints principales implementados:

- `GET /health`
- `GET /api/events`
- `GET /api/events/{id}`
- `POST /api/events/{id}/reservations`, con cabecera obligatoria `Idempotency-Key`
- `POST /api/auth/register`, `POST /api/auth/login`, `POST /api/auth/logout`
- `GET /api/me/reservations`, `GET /api/me/tickets`, `GET /api/me/tickets/{id}`
- `GET/PATCH /api/organizer/events...`
- `GET /api/operator/events`, `POST /api/operator/validate`

No existe un endpoint público para enumerar reservas o entradas. Consulta [docs/autenticacion-y-entradas.md](docs/autenticacion-y-entradas.md) para el modelo de sesión, expiración, permisos y limitaciones.

## Verificación

```bash
./scripts/check-local.sh
```

Consulta [docs/diagnostico-entorno.md](docs/diagnostico-entorno.md), [docs/arquitectura-inicial.md](docs/arquitectura-inicial.md), [infra/aws/README.md](infra/aws/README.md) y [docs/costos-v1.md](docs/costos-v1.md) antes de cualquier despliegue. La configuración de Nginx/systemd está preparada en `deploy/`, pero HTTPS no estará operativo hasta elegir un dominio, obtener un certificado y verificar el servicio públicamente.
