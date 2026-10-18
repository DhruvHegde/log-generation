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

# Trigger batch 1 at 1792323006.712351

# Trigger batch 1 at 1792323091.132698

# Trigger batch 1 at 1792324116.1863601

# Trigger batch 1 at 1792325192.46926

# Trigger batch 2 at 1792325229.6212971

# Trigger batch 3 at 1792325267.5687652

# Trigger batch 4 at 1792325312.0895784

# Trigger batch 5 at 1792325349.8194184

# Trigger batch 6 at 1792325391.099054

# Trigger batch 7 at 1792325434.3026843

# Trigger batch 8 at 1792325482.1096187

# Trigger batch 9 at 1792325530.4024045

# Trigger batch 10 at 1792325579.2561288

# Trigger batch 11 at 1792325622.0445783
