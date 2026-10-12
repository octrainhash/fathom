# Fathom as a server: run it once (on a PC, NAS, Raspberry Pi or cloud machine) and use it from any device with a browser.
#   docker build -t fathom .
#   docker run -p 8777:8777 -v "$HOME/Documents:/data" -v fathom-config:/config fathom
# Then open the link printed in the log (docker logs <container>). Build with  --build-arg WITH_OFFICE=1  to include LibreOffice (+700 MB).
FROM python:3.12-slim
ARG WITH_OFFICE=0
ENV DEBIAN_FRONTEND=noninteractive PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1 \
    FATHOM_HOME=/config FATHOM_ROOTS=/data FATHOM_SERVE=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg p7zip-full libgl1 libglib2.0-0 fonts-dejavu-core curl ca-certificates \
    && if [ "$WITH_OFFICE" = "1" ]; then apt-get install -y --no-install-recommends libreoffice-core libreoffice-writer libreoffice-calc libreoffice-impress; fi \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --prefer-binary -r requirements.txt
COPY . .
RUN mkdir -p /config /data && touch /config/installed-2.ok
VOLUME ["/config", "/data"]
EXPOSE 8777
CMD ["python", "launch.py", "--serve", "--port", "8777"]
