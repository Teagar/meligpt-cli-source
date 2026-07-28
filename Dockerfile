# syntax=docker/dockerfile:1
# --- estágio de build ---------------------------------------------------
FROM python:3.12.7-slim-bookworm AS builder

WORKDIR /build

RUN pip install --no-cache-dir --upgrade pip

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir --prefix=/install .

# --- estágio final (enxuto) ---------------------------------------------
FROM python:3.12.7-slim-bookworm AS runtime

LABEL org.opencontainers.image.title="meligpt-cli" \
      org.opencontainers.image.description="Cliente CLI e servidor HTTP/SSE opcional para o MeliGPT."

# Usuário não-root
RUN groupadd --gid 10001 meligpt \
    && useradd --uid 10001 --gid meligpt --create-home --shell /usr/sbin/nologin meligpt

COPY --from=builder /install /usr/local

ENV MELIGPT_CONFIG_DIR=/data/config \
    MELIGPT_FILES_DIR=/data/files \
    MELIGPT_SECRETS_PATH=/data/config/secrets.env \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN mkdir -p /data/config /data/files \
    && chown -R meligpt:meligpt /data

USER meligpt
WORKDIR /home/meligpt

# Volumes explícitos: credenciais e arquivos locais manipulados pelas ferramentas.
VOLUME ["/data/config", "/data/files"]

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3).status == 200 else 1)" || exit 1

ENTRYPOINT ["python", "-m", "meligpt"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8080"]
