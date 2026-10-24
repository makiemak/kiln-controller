# Rehearsal image for the 25.10.x releases, which run on Raspberry Pi OS
# Bookworm with the system python3 and a pip venv. Debian's own python3
# package is the same 3.11.2 build the Pi uses, and requirements-25.10.txt
# is the Pi's `pip freeze`, so the libraries match the kiln exactly.
#
# The kiln-controller source is mounted at /app at run time (see run.sh),
# so one image rehearses any 25.10.x ref. docker/fakehw is mounted at
# /opt/fakehw and put first on PYTHONPATH to stand in for the GPIO, SPI
# and thermocouple libraries.
FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 python3-venv python3-dev build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-25.10.txt /tmp/requirements-25.10.txt
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --no-deps -r /tmp/requirements-25.10.txt \
    && /opt/venv/bin/pip install --no-cache-dir pytest==8.3.5

ENV PYTHONPATH=/opt/fakehw \
    PYTHONUNBUFFERED=1
WORKDIR /app
EXPOSE 8081
CMD ["/opt/venv/bin/python", "kiln-controller.py"]
