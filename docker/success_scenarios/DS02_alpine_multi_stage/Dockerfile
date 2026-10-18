FROM alpine:3.19 AS builder
WORKDIR /build
COPY src/main.sh .
RUN chmod +x main.sh && ./main.sh > /build/build_artifact.txt

FROM alpine:3.19 AS runtime
WORKDIR /app
COPY --from=builder /build/build_artifact.txt /app/artifact.txt
CMD ["cat", "/app/artifact.txt"]
