FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd -m app && mkdir -p /app/data && chown app /app/data
USER app
ENV INSTRUMENT_DB=/app/data/instruments.db
EXPOSE 8000
CMD ["python", "-m", "instrument_index_mcp.server", "--http", "--host", "0.0.0.0", "--port", "8000"]
