FROM python:3.13-slim AS base

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY evaluation ./evaluation

FROM base AS test
COPY requirements-dev.txt pytest.ini ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY tests ./tests
USER 10001
CMD ["python", "-m", "pytest", "-p", "no:cacheprovider"]

FROM base AS runtime
USER 10001
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0"]
