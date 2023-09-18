import socket
import time
from datetime import datetime

host = "169.254.190.83"
port = 9876


with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.connect((host, port))
    command = "BIAS:DEV4:CURR?".encode()
    sock.settimeout(2)
    errors = 0
    for i in range(1, 1001):
        time.sleep(0.1)
        sock.send(command)
        time.sleep(0.05)
        response = sock.recv(1024).decode("ISO-8859-1").rstrip()
        print(f"[{datetime.now()}]Resp: {response}")
        if "ERROR" in response:
            errors += 1

print(f"Errors: {errors}")


# 0: 3.7%
# 0.05: 2%
# 0.05 + 0.1 cycle: 1.8%
# 0.1: 2.6%
