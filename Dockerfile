FROM python:3.12-slim

# Trazabilidad build<->git (sec G5, cierre anti-drift): se inyectan en build
# time via --build-arg (scripts/deploy_green.sh) y quedan expuestos en
# odoo_health() para poder verificar en caliente que lo desplegado coincide
# con el commit/tag que se PENSABA desplegar.
ARG GIT_COMMIT=unknown
ARG MCP_VERSION=unknown

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MCP_GIT_COMMIT=${GIT_COMMIT} \
    MCP_VERSION=${MCP_VERSION}

WORKDIR /app

# Dependencias del sistema minimas
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependencias Python primero (cache layer)
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install \
    "mcp[cli]==1.27.1" \
    "uvicorn>=0.29" \
    "pyyaml>=6.0"

# Copiar codigo. config/ incluye apl_labels.yaml (ticket 737, ADR-017):
# fuente unica de IDs de etiquetas APL 2.0, sin secretos, horneada en la
# imagen. Cambio de ID = commit + rebuild, nunca edicion en caliente.
COPY app/ ./app/
COPY config/ ./config/
COPY scripts/ ./scripts/

# Usuario no-root
RUN useradd -m -u 1000 mcpuser
USER mcpuser

EXPOSE 8000

# Healthcheck via TCP — el endpoint /mcp requiere headers MCP especificos
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD python3 -c "import socket; s=socket.socket(); s.settimeout(2); s.connect(('127.0.0.1',8000)); s.close()"

CMD ["python", "-m", "app.odoo_mcp_remote"]
