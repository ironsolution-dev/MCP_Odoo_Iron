FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencias del sistema minimas
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependencias Python primero (cache layer)
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install \
    "fastmcp>=0.2.0" \
    "httpx>=0.27" \
    "pyyaml>=6.0"

# Copiar codigo
COPY app/ ./app/
COPY scripts/ ./scripts/

# Usuario no-root
RUN useradd -m -u 1000 mcpuser
USER mcpuser

EXPOSE 8000

# Healthcheck simple (verifica que el puerto responde)
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["python", "-m", "app.odoo_mcp_remote"]
