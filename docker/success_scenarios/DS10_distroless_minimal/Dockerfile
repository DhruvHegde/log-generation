FROM alpine:3.19 AS preparer
WORKDIR /stage
RUN echo "Minimal static distroless configuration" > /stage/static_config.txt

FROM gcr.io/distroless/static-debian12:latest
COPY --from=preparer /stage/static_config.txt /etc/static_config.txt
USER nonroot:nonroot
