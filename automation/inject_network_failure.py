import argparse
from pathlib import Path

TEST_FILE = Path("tests/test_app.py")

NETWORK_FAILURE_MUTATIONS = {
    "dns_resolution_failure": '''
def test_dns_resolution_failure():
    """Injected synthetic DNS resolution failure."""
    import socket
    target = "nonexistent-domain-abc123.example.com"
    operation = "socket.gethostbyname(DNS resolution)"
    retries = 3
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            socket.gethostbyname(target)
            return
        except socket.gaierror as e:
            last_error = e
    print(
        f"NETWORK ERROR: DNS resolution failed\\n"
        f"  Target host: {target}\\n"
        f"  Operation: {operation}\\n"
        f"  Retries: {retries}/{retries}\\n"
        f"  Error: [Errno -3] Could not resolve host '{target}': {last_error}"
    )
    raise last_error
''',
    "connection_refused": '''
def test_connection_refused():
    """Injected synthetic connection refused error."""
    import socket
    target = "127.0.0.1:12345"
    operation = "TCP connect to closed port"
    retries = 3
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            sock.connect(("127.0.0.1", 12345))
            sock.close()
            return
        except (ConnectionRefusedError, OSError) as e:
            last_error = e
    print(
        f"NETWORK ERROR: Connection refused\\n"
        f"  Target host: {target}\\n"
        f"  Operation: {operation}\\n"
        f"  Retries: {retries}/{retries}\\n"
        f"  Error: ConnectionRefusedError [Errno 111] Connection refused: {last_error}"
    )
    raise last_error
''',
    "connection_timeout": '''
def test_connection_timeout():
    """Injected synthetic connection timeout error."""
    import socket
    target = "10.255.255.1:80"
    operation = "TCP connect with 0.1s timeout"
    retries = 3
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.1)
            sock.connect(("10.255.255.1", 80))
            sock.close()
            return
        except (socket.timeout, OSError) as e:
            last_error = e
    print(
        f"NETWORK ERROR: Connection timeout\\n"
        f"  Target host: {target}\\n"
        f"  Operation: {operation}\\n"
        f"  Retries: {retries}/{retries}\\n"
        f"  Error: ConnectTimeout/ETIMEDOUT Operation timed out: {last_error}"
    )
    raise last_error
''',
    "connection_reset": '''
def test_connection_reset():
    """Injected synthetic connection reset error."""
    target = "peer"
    operation = "TCP connection reset by peer"
    retries = 3
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            raise ConnectionResetError(104, "Connection reset by peer")
        except ConnectionResetError as e:
            last_error = e
    print(
        f"NETWORK ERROR: Connection reset\\n"
        f"  Target host: {target}\\n"
        f"  Operation: {operation}\\n"
        f"  Retries: {retries}/{retries}\\n"
        f"  Error: ConnectionResetError [Errno 104] Connection reset by peer: {last_error}"
    )
    raise last_error
''',
    "tls_handshake_failure": '''
def test_tls_handshake_failure():
    """Injected synthetic TLS handshake failure."""
    import ssl
    target = "self-signed certificate (_ssl.c:1000)"
    operation = "TLS handshake certificate verification"
    retries = 3
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            raise ssl.SSLCertVerificationError(1, "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate (_ssl.c:1000)")
        except ssl.SSLCertVerificationError as e:
            last_error = e
    print(
        f"NETWORK ERROR: TLS handshake failure\\n"
        f"  Target host: {target}\\n"
        f"  Operation: {operation}\\n"
        f"  Retries: {retries}/{retries}\\n"
        f"  Error: SSL: CERTIFICATE_VERIFY_FAILED certificate verify failed: self-signed certificate: {last_error}"
    )
    raise last_error
''',
    "remote_server_5xx": '''
def test_remote_server_5xx():
    """Injected synthetic remote server 5xx error."""
    import urllib.error
    target = "https://api.service.internal/v1/data"
    operation = "HTTP GET (503 Service Unavailable)"
    retries = 3
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            raise urllib.error.HTTPError(target, 503, "Service Unavailable: Backend cluster unresponsive", {}, None)
        except urllib.error.HTTPError as e:
            last_error = e
    print(
        f"NETWORK ERROR: Remote server 5xx error\\n"
        f"  Target host: {target}\\n"
        f"  Operation: {operation}\\n"
        f"  Retries: {retries}/{retries}\\n"
        f"  Error: HTTP 503 Service Unavailable: Backend cluster unresponsive: {last_error}"
    )
    raise last_error
''',
    "rate_limit_exceeded": '''
def test_rate_limit_exceeded():
    """Injected synthetic rate limit 429 error."""
    import urllib.error
    target = "https://api.github.com/resource"
    operation = "HTTP GET (429 Too Many Requests)"
    retries = 3
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            raise urllib.error.HTTPError(target, 429, "Too Many Requests: API rate limit exceeded", {}, None)
        except urllib.error.HTTPError as e:
            last_error = e
    print(
        f"NETWORK ERROR: Rate limit exceeded\\n"
        f"  Target host: {target}\\n"
        f"  Operation: {operation}\\n"
        f"  Retries: {retries}/{retries}\\n"
        f"  Error: HTTP 429 Too Many Requests: API rate limit exceeded: {last_error}"
    )
    raise last_error
''',
    "package_repo_unreachable": '''
def test_package_repo_unreachable():
    """Injected synthetic package repository unreachable error."""
    import urllib.error
    target = "https://pypi.org/simple/requests/"
    operation = "HTTP GET (502 Bad Gateway)"
    retries = 3
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            raise urllib.error.HTTPError(target, 502, "Bad Gateway: PyPI upstream CDN connection failed", {}, None)
        except urllib.error.HTTPError as e:
            last_error = e
    print(
        f"NETWORK ERROR: Package repository unreachable\\n"
        f"  Target host: {target}\\n"
        f"  Operation: {operation}\\n"
        f"  Retries: {retries}/{retries}\\n"
        f"  Error: HTTP 502 Bad Gateway: PyPI upstream CDN connection failed: {last_error}"
    )
    raise last_error
''',
    "external_service_outage": '''
def test_external_service_outage():
    """Injected synthetic external service outage."""
    import urllib.error
    target = "https://auth.service.internal/oauth/token"
    operation = "External service connection"
    retries = 3
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            raise urllib.error.URLError(f"Connection refused by external service: {target}")
        except urllib.error.URLError as e:
            last_error = e
    print(
        f"NETWORK ERROR: External service outage\\n"
        f"  Target host: {target}\\n"
        f"  Operation: {operation}\\n"
        f"  Retries: {retries}/{retries}\\n"
        f"  Error: Connection refused by external service: {target}: {last_error}"
    )
    raise last_error
''',
}

def inject(failure_type: str):
    if failure_type in ("success", "valid_python_project"):
        baseline = TEST_FILE.read_text(encoding="utf-8")
        if "# --- SYNTHETIC F7 NETWORK FAILURE MUTATION ---" in baseline:
            clean_baseline = baseline.split("# --- SYNTHETIC F7 NETWORK FAILURE MUTATION ---")[0].rstrip()
            TEST_FILE.write_text(clean_baseline + "\n", encoding="utf-8")
        print(f"[Success Run] Maintained clean baseline in {TEST_FILE}")
        return

    if failure_type not in NETWORK_FAILURE_MUTATIONS:
        raise ValueError(f"Unknown failure type: {failure_type}. Valid: {list(NETWORK_FAILURE_MUTATIONS.keys())}")

    baseline = TEST_FILE.read_text(encoding="utf-8")
    if "# --- SYNTHETIC F7 NETWORK FAILURE MUTATION ---" in baseline:
        baseline = baseline.split("# --- SYNTHETIC F7 NETWORK FAILURE MUTATION ---")[0].rstrip()

    mutation = NETWORK_FAILURE_MUTATIONS[failure_type]
    mutated_content = f"{baseline}\n\n# --- SYNTHETIC F7 NETWORK FAILURE MUTATION ---\n{mutation}"
    TEST_FILE.write_text(mutated_content, encoding="utf-8")
    print(f"[Mutation Injected] Successfully injected {failure_type} into {TEST_FILE}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inject synthetic network failure mutation into tests/test_app.py")
    parser.add_argument("--error-type", type=str, required=True, help="Network failure type to inject")
    args = parser.parse_args()
    inject(args.error_type)
