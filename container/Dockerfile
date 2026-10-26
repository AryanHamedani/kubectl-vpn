FROM alpine:3.23
RUN apk add --no-cache openvpn python3 iptables iproute2
COPY entrypoint.py proxy.py /app/
ENTRYPOINT ["python3", "/app/entrypoint.py"]
