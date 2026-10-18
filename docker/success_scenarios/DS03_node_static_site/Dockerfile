FROM node:20-alpine AS bundler
WORKDIR /build
COPY src/index.html .
RUN echo "<!-- Processed by Node Bundler -->" >> index.html

FROM nginx:alpine
COPY --from=bundler /build/index.html /usr/share/nginx/html/index.html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
