# One image for the API and the workers. The container runs the API by default; the workers app sets its
# command to `python -m diucs.bootstrap.workers_main` (see infra/azure/apps.bicep).
FROM python:3.14-slim AS build
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONDONTWRITEBYTECODE=1
RUN pip install --no-cache-dir uv==0.13.6
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

FROM python:3.14-slim
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN useradd --system --uid 10001 --no-create-home diucs
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY --from=build /app/src /app/src
# Reference data the code reads at run time (settings.py resolves these relative to /app).
COPY data /app/data
COPY profiles /app/profiles
COPY terminology /app/terminology
USER 10001
EXPOSE 8000
CMD ["python", "-m", "diucs.bootstrap.api_main"]
