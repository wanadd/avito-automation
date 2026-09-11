FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY apps ./apps
RUN pip install --no-cache-dir ".[test]"

COPY alembic.ini ./
COPY alembic ./alembic

ENV PYTHONPATH=/app/apps/api

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
