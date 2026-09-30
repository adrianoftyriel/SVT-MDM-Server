# Per-arch HA base image, selected with the BUILD_ARCH build arg the
# Supervisor passes on every add-on build. This replaces the retired
# build.yaml `build_from` map with the same images it pinned (Alpine 3.19
# bases); the generic ghcr.io/home-assistant/base multi-arch image only
# exists from 3.21, and this change must not alter the deployed runtime.
ARG BUILD_ARCH
FROM ghcr.io/home-assistant/${BUILD_ARCH}-base:3.19

# Alpine-based HA base image. bashio is already available.
# py3-cryptography comes prebuilt from Alpine, avoiding a slow source build
# of `cryptography` on musl during pip install.
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
