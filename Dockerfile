FROM python:3.12-slim
RUN addgroup --system prahari && adduser --system --ingroup prahari prahari
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN chown -R prahari:prahari /app
USER prahari
CMD ["python", "main.py", "serve"]
