import argparse
from pathlib import Path

TEST_FILE = Path("tests/test_app.py")

NETWORK_FAILURE_MUTATIONS = {
    "dns_resolution_failure": """
def test_dns_resolution_failure():
    \"\"\"Injected synthetic DNS resolution failure.\"\"\"
    import socket
    socket.gethostbyname("nonexistent-domain-abc123.example.com")
""",
    "connection_refused": """
def test_connection_refused():
    \"\"\"Injected synthetic connection refused error.\"\"\"
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    sock.connect(("127.0.0.1", 12345))  # Port unlikely to be listening
    sock.close()
""",
    "connection_timeout": """
def test_connection_timeout():
    \"\"\"Injected synthetic connection timeout error.\"\"\"
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.1)  # Very short timeout
    # Try to connect to a non-routable IP address
    sock.connect(("10.255.255.1", 80))
    sock.close()
""",
    "read_timeout": """
def test_read_timeout():
    \"\"\"Injected synthetic read timeout error.\"\"\"
    import urllib.request
    import urllib.error
    try:
        # URL that will accept connection but not send data quickly
        urllib.request.urlopen("http://httpbin.org/delay/10", timeout=1)
    except urllib.error.URLError as e:
        raise TimeoutError("Read timeout occurred") from e
""",
    "remote_server_503": """
def test_remote_server_503():
    \"\"\"Injected synthetic 503 Service Unavailable error.\"\"\"
    import urllib.request
    import urllib.error
    try:
        # httpbin.org/status/503 returns a 503 status code
        urllib.request.urlopen("http://httpbin.org/status/503")
    except urllib.error.HTTPError as e:
        if e.code == 503:
            raise  # Re-raise the 503 error
        else:
            raise
""",
    "pypi_unreachable": """
def test_pypi_unreachable():
    \"\"\"Injected synthetic PyPI unreachable error.\"\"\"
    import urllib.request
    import urllib.error
    # Try to access a non-existent PyPI endpoint that should timeout
    urllib.request.urlopen("https://pypi.org/packages/nonexistent/package-999.999.tar.gz", timeout=2)
""",
}

def inject(failure_type: str):
    if failure_type not in NETWORK_FAILURE_MUTATIONS:
        raise ValueError(f"Unknown failure type: {failure_type}. Valid: {list(NETWORK_FAILURE_MUTATIONS.keys())}")
    
    baseline = TEST_FILE.read_text(encoding="utf-8")
    mutation = NETWORK_FAILURE_MUTATIONS[failure_type]
    mutated_content = f"{baseline}\n\n# --- SYNTHETIC F7 NETWORK FAILURE MUTATION ---\n{mutation}"
    TEST_FILE.write_text(mutated_content, encoding="utf-8")
    print(f"[Mutation Injected] Successfully injected {failure_type} into {TEST_FILE}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inject synthetic network failure mutation into tests/test_app.py")
    parser.add_argument("--failure-type", type=str, required=True, help="Network failure type to inject")
    args = parser.parse_args()
    inject(args.failure_type)
