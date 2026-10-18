FROM alpine:3.19
WORKDIR /app
RUN --mount=type=cache,target=/var/cache/build \
    echo "Writing cached artifact to build cache" > /var/cache/build/cache_marker.txt && \
    echo "Cache mount exercised successfully" > /app/cache_status.txt
CMD ["cat", "/app/cache_status.txt"]
