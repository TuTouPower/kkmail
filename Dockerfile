# Deprecated. Use Dockerfile.mail-core:
#   docker compose -f docker-compose.mail-core.yml up --build
FROM alpine:3.20
CMD ["sh", "-c", "echo Use Dockerfile.mail-core / docker-compose.mail-core.yml; exit 1"]
