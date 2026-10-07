FROM python:3.12-slim

# تنظیم میرور APT
RUN if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i 's|deb.debian.org|mirror.arvancloud.ir|g' /etc/apt/sources.list.d/debian.sources; \
    else \
        sed -i 's|deb.debian.org|mirror.arvancloud.ir|g' /etc/apt/sources.list; \
    fi

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

<<<<<<< HEAD
ARG PIP_INDEX_URL
=======
# تنظیم میرور PIP
RUN pip config set global.index-url https://mirror-pypi.runflare.com/simple && \
    pip config set global.trusted-host mirror-pypi.runflare.com
>>>>>>> 4c801c167e3eb9d2b5be1549952bdcf03c6d22cd

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .