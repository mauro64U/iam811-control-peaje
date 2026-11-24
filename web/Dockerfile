# ==============================================================================
# Dockerfile Unificado (Frontend React + Backend FastAPI) para Subdominio HTTPS
# Desplegable en Render, Railway, Fly.io, Koyeb o VPS con un solo contenedor.
# ==============================================================================

# Etapa 1: Compilar Frontend React + Vite + TailwindCSS
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
ARG VITE_GOOGLE_CLIENT_ID=159830757831-du48o4vm4c7uigujttelj58dvlktbhpq.apps.googleusercontent.com
ARG VITE_API_BASE_URL=/api/v1
ENV VITE_GOOGLE_CLIENT_ID=$VITE_GOOGLE_CLIENT_ID
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
COPY frontend/package.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# Etapa 2: Servidor Backend FastAPI que sirve la API REST (/api/v1) y el Panel Web
FROM python:3.11-slim
WORKDIR /app/backend

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
