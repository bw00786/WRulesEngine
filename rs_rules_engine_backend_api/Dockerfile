# Stage 1: Builder
FROM python:3.9-slim as builder

# Install build dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Stage 2: Runtime
FROM python:3.9-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=31843

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Create the /app directory and set permissions
RUN mkdir -p /app && useradd -m appuser && chown -R appuser /app

# Switch to the appuser
USER appuser

# Copy installed Python packages and application code from the builder stage
COPY --from=builder --chown=appuser /root/.local /home/appuser/.local
COPY --from=builder --chown=appuser /app /app

# Add .local/bin to PATH
ENV PATH=/home/appuser/.local/bin:$PATH

# Expose the application port
EXPOSE 31843

# Run the application
CMD ["gunicorn", "--bind", "0.0.0.0:31843", "--workers", "1", "--worker-class", "uvicorn.workers.UvicornWorker", "main:app"]