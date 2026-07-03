FROM python:3.12-slim

ARG GIT_COMMIT=""
ARG GIT_COMMIT_SHORT=""
ARG BUILD_DATE=""
ARG BUILD_REF=""
ARG BUILD_NUMBER=""
ARG BUILD_REPO=""

ENV GIT_COMMIT=${GIT_COMMIT}
ENV GIT_COMMIT_SHORT=${GIT_COMMIT_SHORT}
ENV BUILD_DATE=${BUILD_DATE}
ENV BUILD_REF=${BUILD_REF}
ENV BUILD_NUMBER=${BUILD_NUMBER}
ENV BUILD_REPO=${BUILD_REPO}
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

RUN apt-get update && apt-get install -y --no-install-recommends curl procps tzdata \
    && rm -rf /var/lib/apt/lists/*

# Copy only dependency files first (layer cached if deps unchanged)
COPY pyproject.toml uv.lock ./

# Install dependencies (cached layer when deps unchanged)
RUN uv sync --frozen --no-dev --no-install-project

# Copy application code (only this layer rebuilds on code changes)
COPY . .

# Install the project itself (fast - deps already installed)
RUN uv sync --frozen --no-dev

RUN mkdir -p /app/data /app/backups /app/staticfiles

# Use a throwaway build-only SECRET_KEY so collectstatic does not generate and
# bake a persistent /app/data/.secret_key into the image layer. Remove any key
# file just in case, so runtime generates/uses its own.
RUN SECRET_KEY=build-time-only uv run python manage.py collectstatic --noinput \
    && rm -f /app/data/.secret_key

# Make entrypoint executable
RUN chmod +x /app/entrypoint.sh

# Run as non-root user (ADR-0001). Create appuser and hand it ownership of the
# whole app tree, including the runtime-writable data/, backups/, and staticfiles
# dirs. NOTE: ./data and ./backups are bind mounts in docker-compose.yml owned by
# the host user; running as uid 1000 requires those host dirs be writable by uid
# 1000 (chown on host or a PUID pattern) or writes will fail.
RUN useradd -m -u 1000 appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
