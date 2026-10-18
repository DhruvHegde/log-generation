FROM debian:bookworm-slim
LABEL maintainer="capstone-team" scenario="DS04" version="1.0"
ENV APP_MODE=production \
    APP_PORT=8080 \
    APP_ROOT=/opt/app
WORKDIR /opt/app
RUN mkdir -p config data logs
COPY config/settings.conf ./config/settings.conf
CMD ["cat", "./config/settings.conf"]
