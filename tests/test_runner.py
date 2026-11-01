"""Regressions for the local process harness, independent of auth servers."""

import socket
import unittest

from conformance import require_free_port


class PortProbeTests(unittest.TestCase):
    def test_detects_an_active_listener(self):
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            with self.assertRaises(RuntimeError):
                require_free_port(listener.getsockname()[1])

    def test_allows_a_port_after_its_server_closed(self):
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            listener.listen(1)
            with socket.create_connection(("127.0.0.1", port)) as client:
                accepted, _ = listener.accept()
                # The server closes first, leaving its endpoint in TIME_WAIT.
                accepted.close()
                self.assertEqual(client.recv(1), b"")
        require_free_port(port)


if __name__ == "__main__":
    unittest.main()
