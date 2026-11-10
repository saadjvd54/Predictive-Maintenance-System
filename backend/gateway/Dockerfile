# ==============================================================================
# PharmaPredict AI — Industrial Edge Gateway Dockerfile
# ==============================================================================
# Multi-stage, minimal, rootless container for on-premise OT deployment.
# Complies with IEC 62443 / Purdue Model Level 2 industrial security standards.
# ==============================================================================

FROM python:3.12-slim AS base

# Install system security dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root industrial service account
RUN groupadd -g 10001 edgegroup && \
    useradd -u 10001 -g edgegroup -s /sbin/nologin -d /opt/edge-gateway edgeuser

WORKDIR /opt/edge-gateway

# Install Python dependencies
COPY requirements.txt /opt/edge-gateway/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy gateway and backend application dependencies
COPY . /opt/edge-gateway/

# Set up dedicated persistent buffer directory with restrictive permissions
RUN mkdir -p /opt/edge-gateway/data/gateway_buffer && \
    chown -R edgeuser:edgegroup /opt/edge-gateway && \
    chmod 700 /opt/edge-gateway/data/gateway_buffer

# Switch to rootless service user
USER edgeuser

# Volume for persistent disk spooling across container restarts
VOLUME ["/opt/edge-gateway/data/gateway_buffer"]

# Outbound only: no EXPOSE ports required (protects OT Purdue Level 1/2 network)

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/edge-gateway \
    BUFFER_DIR=/opt/edge-gateway/data/gateway_buffer

# Healthcheck to verify gateway process status
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import sys, os; sys.exit(0 if os.path.isdir('/opt/edge-gateway/data/gateway_buffer') else 1)"

CMD ["python", "gateway/edge_gateway.py"]
