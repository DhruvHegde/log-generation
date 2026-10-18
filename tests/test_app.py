from app import add

def test_add():
    assert add(2, 3) == 5


# --- SYNTHETIC F7 NETWORK FAILURE MUTATION ---

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
        f"NETWORK ERROR: Connection timeout\n"
        f"  Target host: {target}\n"
        f"  Operation: {operation}\n"
        f"  Retries: {retries}/{retries}\n"
        f"  Error: ConnectTimeout/ETIMEDOUT Operation timed out: {last_error}"
    )
    raise last_error

# Trigger batch 1 at 1792322556.9923973

# Trigger batch 1 at 1792322649.2607403
