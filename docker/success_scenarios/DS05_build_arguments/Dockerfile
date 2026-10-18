FROM alpine:3.19
ARG APP_VERSION=1.0.0
ARG BUILD_ENV=development
ENV APP_VERSION=${APP_VERSION} \
    BUILD_ENV=${BUILD_ENV}
WORKDIR /app
RUN echo "Building version ${APP_VERSION} in environment ${BUILD_ENV}" > /app/build_info.txt
CMD ["cat", "/app/build_info.txt"]
