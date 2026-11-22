FROM python:3.12-slim-bookworm@sha256:d97792894a6a4162cae14da44542a83c75e56c77a27b92d58f3f83b7bc961292
WORKDIR /app
COPY . /app/engineering_council/
USER 65532:65532
ENV PYTHONDONTWRITEBYTECODE=1
ENTRYPOINT ["python", "-m", "engineering_council.council"]
