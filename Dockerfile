FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
RUN addgroup --system prahari && adduser --system --ingroup prahari prahari
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir .
RUN chown -R prahari:prahari /app
USER prahari
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/pycache TMPDIR=/tmp
CMD ["python", "main.py", "serve"]
