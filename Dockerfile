FROM node:24-bookworm-slim AS frontend
WORKDIR /build/frontend
COPY frontend/ ./
COPY scripts/versioning.mjs scripts/versioning.d.mts /build/scripts/
COPY version.json CHANGELOG.md /build/
RUN npm ci --strict-peer-deps
ARG ORG_COMMIT_SHA=unknown
ARG ORG_RELEASE_TAG=
ARG ORG_SOURCE_DIRTY=
RUN node /build/scripts/versioning.mjs build-info --output /build/build-info.json
ENV ORG_BUILD_INFO_FILE=/build/build-info.json
RUN npm run build

FROM python:3.13-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/srv/backend:/srv
WORKDIR /srv/backend
COPY backend/requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY backend/ ./
COPY --from=frontend /build/build-info.json /srv/backend/app/_build_info.json
RUN pip install --no-cache-dir --no-deps .
COPY --from=frontend /build/frontend/dist /srv/frontend/dist
COPY deploy/ /srv/deploy/
RUN useradd --create-home --uid 10001 organization
USER organization
EXPOSE 8000
CMD ["python", "-m", "deploy.supervise"]
