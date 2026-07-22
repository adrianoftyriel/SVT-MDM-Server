ARG BUILD_FROM
FROM ${BUILD_FROM}

# Alpine-based HA base image. bashio is already available.
# py3-cryptography comes prebuilt from Alpine, avoiding a slow/failing source
# build of `cryptography` on musl/armv7 during pip install.
RUN apk add --no-cache python3 py3-pip py3-cryptography

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_BREAK_SYSTEM_PACKAGES=1

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir -r /app/requirements.txt

# Application code.
COPY app /app/app

# Add-on entrypoint.
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]
