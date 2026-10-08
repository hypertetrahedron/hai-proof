# hai-proof egress allowlist sidecar (DESIGN 3.5): tinyproxy filtering CONNECT by hostname.
FROM alpine:3.20
RUN apk add --no-cache tinyproxy
COPY entrypoint.sh /entrypoint.sh
RUN chmod 0755 /entrypoint.sh && mkdir -p /etc/tinyproxy
LABEL hai-proof.role=proxy
EXPOSE 3128
ENTRYPOINT ["/entrypoint.sh"]
