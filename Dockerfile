FROM gcc:latest

# Install Python and dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

# Copy application files
COPY app.py index.html ./

# Create temp directory for compilations
RUN mkdir -p /tmp/openmp_compiler && chmod 777 /tmp/openmp_compiler

# Expose port
EXPOSE 5000

# Set environment variables
ENV FLASK_APP=app.py
ENV PORT=5000
ENV PYTHONUNBUFFERED=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD ["python3", "-c", "import os, urllib.request; urllib.request.urlopen(f\"http://localhost:{os.environ.get('PORT','5000')}/health\").read()"]

# Run the application
CMD ["python3", "app.py"]
