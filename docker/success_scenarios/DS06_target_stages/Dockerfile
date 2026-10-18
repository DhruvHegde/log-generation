FROM alpine:3.19 AS base
WORKDIR /app
RUN echo "Base stage initialized" > /app/base_marker.txt

FROM base AS dev_stage
RUN echo "Development dependencies and debug tools" > /app/dev_marker.txt

FROM base AS test_stage
RUN echo "Test execution and test harness" > /app/test_marker.txt

FROM base AS release_stage
RUN echo "Release stage packaging finalized" > /app/release_marker.txt
CMD ["cat", "/app/release_marker.txt"]
