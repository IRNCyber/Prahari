FROM python:3.12-slim
WORKDIR /workspace
COPY . .
RUN pip install --no-cache-dir ".[dev]"
ENV PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS="-p no:cacheprovider"
CMD ["python", "-m", "verifier.sandbox_runner"]
