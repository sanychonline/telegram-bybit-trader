FROM python:3.11-slim

WORKDIR /opt/bot
COPY app/requirements.txt ./app/requirements.txt
RUN pip install --no-cache-dir -r app/requirements.txt
COPY app ./app
RUN mkdir -p /opt/bot/data
WORKDIR /opt/bot/app
CMD ["python", "main.py"]
