FROM node:24-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/srv/backend:/srv
WORKDIR /srv/backend
COPY backend/requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY backend/ ./
RUN pip install --no-cache-dir --no-deps .
COPY --from=frontend /build/dist /srv/frontend/dist
COPY deploy/ /srv/deploy/
RUN useradd --create-home --uid 10001 organization
USER organization
EXPOSE 8000
CMD ["python", "-m", "deploy.supervise"]
