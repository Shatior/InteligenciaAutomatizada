FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    TZ=UTC

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# Chromium y sus dependencias de sistema para los niveles de navegador de Scrapling.
RUN scrapling install && rm -rf /var/lib/apt/lists/*

COPY . .

# El comando por defecto es el panel; el servicio "motor" lo sobreescribe en Railway
# con: python -m intel motor
CMD ["python", "-m", "intel", "panel"]
