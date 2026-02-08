"""Protocol handshake client.

Implements the 4-phase handshake: HELLO, CHALLENGE, RESPONSE, READY.
The correct order is critical for the server to accept the connection.

BUG: The perform_handshake() method calls steps out of order --
it sends CHALLENGE before HELLO, which the server rejects.
"""

import socket


class HandshakeClient:
    """Client that performs the protocol handshake."""

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.sock = None

    def connect(self):
        """Open a raw TCP connection."""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((self.host, self.port))

    def send_hello(self):
        """Phase 1: Send HELLO with client identifier."""
        self.sock.sendall(b"HELLO client-v1\n")

    def send_challenge(self):
        """Phase 2: Send CHALLENGE token for authentication."""
        self.sock.sendall(b"CHALLENGE token-abc\n")

    def send_response(self):
        """Phase 3: Send RESPONSE with signed nonce."""
        self.sock.sendall(b"RESPONSE signed-nonce\n")

    def send_ready(self):
        """Phase 4: Send READY to complete handshake."""
        self.sock.sendall(b"READY\n")

    def perform_handshake(self):
        """Execute the full handshake sequence.

        BUG: CHALLENGE is sent before HELLO. The correct order is:
        HELLO -> CHALLENGE -> RESPONSE -> READY
        """
        self.connect()
        self.send_challenge()  # BUG: should be send_hello() first
        self.send_hello()
        self.send_response()
        self.send_ready()
