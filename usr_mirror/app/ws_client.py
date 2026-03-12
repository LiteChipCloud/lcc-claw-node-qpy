import ubinascii
import uhashlib
import uos
import usocket
import ustruct

try:
    import ussl
except Exception:
    ussl = None


GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OP_TEXT = 0x1
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA


class WsError(Exception):
    pass


class WsClosed(WsError):
    pass


class WsTimeout(WsError):
    pass


class WsClient(object):

    def __init__(self):
        self.sock = None
        self.url = ""
        self.host = ""
        self.port = 0
        self.path = "/"
        self.secure = False
        self.open = False

    def _parse_url(self, url):
        raw = (url or "").strip()
        secure = False
        if raw.startswith("ws://"):
            raw = raw[5:]
        elif raw.startswith("wss://"):
            raw = raw[6:]
            secure = True
        else:
            raise ValueError("unsupported websocket scheme")

        slash = raw.find("/")
        if slash >= 0:
            host_part = raw[:slash]
            path = raw[slash:] or "/"
        else:
            host_part = raw
            path = "/"

        if ":" in host_part:
            host, port_text = host_part.split(":", 1)
            port = int(port_text)
        else:
            host = host_part
            port = 443 if secure else 80

        return secure, host, port, path

    def connect(self, url, timeout_sec, headers=None, server_hostname=None):
        self.secure, self.host, self.port, self.path = self._parse_url(url)
        self.url = url

        if headers is None:
            headers = {}

        sock = usocket.socket()
        sock.settimeout(timeout_sec)
        try:
            addr = usocket.getaddrinfo(self.host, self.port)[0][-1]
            sock.connect(addr)
            if self.secure:
                if ussl is None:
                    raise WsError("ussl unavailable")
                tls_host = server_hostname or self.host
                sock = ussl.wrap_socket(sock, server_hostname=tls_host)
                sock.settimeout(timeout_sec)

            sec_key = self._random_key()
            request_lines = [
                "GET " + self.path + " HTTP/1.1",
                "Host: " + self.host + ":" + str(self.port),
                "Connection: Upgrade",
                "Upgrade: websocket",
                "Sec-WebSocket-Key: " + sec_key,
                "Sec-WebSocket-Version: 13",
            ]
            for key in headers:
                request_lines.append(str(key) + ": " + str(headers[key]))
            request_lines.append("")
            request_lines.append("")
            self._write_all(sock, "\r\n".join(request_lines).encode("utf-8"))

            status_line = self._read_line(sock)
            if (not status_line) or (not status_line.startswith("HTTP/1.1 101 ")):
                raise WsError("handshake failed: " + (status_line or "no status"))

            response_headers = {}
            while True:
                line = self._read_line(sock)
                if line is None:
                    raise WsError("handshake header timeout")
                if line == "":
                    break
                pos = line.find(":")
                if pos > 0:
                    key = line[:pos].strip().lower()
                    value = line[pos + 1:].strip()
                    response_headers[key] = value

            expected_accept = self._expected_accept(sec_key)
            actual_accept = response_headers.get("sec-websocket-accept", "")
            if expected_accept and actual_accept and expected_accept != actual_accept:
                raise WsError("invalid websocket accept")

            self.sock = sock
            self.open = True
        except Exception:
            try:
                sock.close()
            except Exception:
                pass
            raise

    def settimeout_ms(self, timeout_ms):
        if self.sock:
            if timeout_ms is None:
                self.sock.settimeout(None)
            else:
                seconds = float(timeout_ms) / 1000.0
                if seconds <= 0:
                    seconds = 0.001
                self.sock.settimeout(seconds)

    def send_text(self, text):
        if not self.open or self.sock is None:
            raise WsClosed("websocket closed")
        if isinstance(text, bytes):
            payload = text
        else:
            payload = str(text).encode("utf-8")
        self._write_frame(OP_TEXT, payload)

    def recv_text(self, timeout_ms):
        if not self.open or self.sock is None:
            raise WsClosed("websocket closed")
        self.settimeout_ms(timeout_ms)

        while self.open:
            fin, opcode, payload = self._read_frame()
            if not fin:
                raise WsError("fragmented frame unsupported")
            if opcode == OP_TEXT:
                return payload.decode("utf-8")
            if opcode == OP_CLOSE:
                self._close_internal()
                raise WsClosed("server closed websocket")
            if opcode == OP_PING:
                self._write_frame(OP_PONG, payload)
                continue
            if opcode == OP_PONG:
                continue
            raise WsError("unsupported opcode")

        raise WsClosed("websocket closed")

    def close(self):
        if not self.open:
            return
        try:
            self._write_frame(OP_CLOSE, ustruct.pack("!H", 1000))
        except Exception:
            pass
        self._close_internal()

    def _close_internal(self):
        self.open = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        self.sock = None

    def _random_key(self):
        return self._b64(uos.urandom(16))

    def _expected_accept(self, sec_key):
        digest = self._sha1_bytes((sec_key + GUID).encode("utf-8"))
        return self._b64(digest)

    def _sha1_bytes(self, data):
        ctor = getattr(uhashlib, "SHA1", None)
        if ctor:
            return ctor(data).digest()

        ctor = getattr(uhashlib, "sha1", None)
        if ctor:
            try:
                return ctor(data).digest()
            except TypeError:
                hasher = ctor()
                hasher.update(data)
                return hasher.digest()

        new_fn = getattr(uhashlib, "new", None)
        if new_fn:
            hasher = new_fn("sha1")
            hasher.update(data)
            return hasher.digest()

        raise WsError("sha1 unavailable")

    def _b64(self, raw):
        return ubinascii.b2a_base64(raw).decode("utf-8").strip()

    def _read_line(self, sock):
        data = bytearray()
        while True:
            chunk = self._read_exact(sock, 1)
            if chunk is None:
                return None
            if chunk == b"\n":
                break
            if chunk != b"\r":
                data.extend(chunk)
        return bytes(data).decode("utf-8")

    def _read_frame(self):
        header = self._read_exact(self.sock, 2)
        if header is None:
            raise WsClosed("socket closed")
        byte1, byte2 = ustruct.unpack("!BB", header)
        fin = bool(byte1 & 0x80)
        opcode = byte1 & 0x0F
        masked = bool(byte2 & 0x80)
        length = byte2 & 0x7F

        if length == 126:
            raw_length = self._read_exact(self.sock, 2)
            if raw_length is None:
                raise WsClosed("socket closed")
            length = ustruct.unpack("!H", raw_length)[0]
        elif length == 127:
            raw_length = self._read_exact(self.sock, 8)
            if raw_length is None:
                raise WsClosed("socket closed")
            length = ustruct.unpack("!Q", raw_length)[0]

        mask_key = None
        if masked:
            mask_key = self._read_exact(self.sock, 4)
            if mask_key is None:
                raise WsClosed("socket closed")

        payload = self._read_exact(self.sock, length)
        if payload is None:
            raise WsClosed("socket closed")

        if masked:
            payload = self._mask_bytes(payload, mask_key)

        return fin, opcode, payload

    def _write_frame(self, opcode, payload):
        if payload is None:
            payload = b""
        fin = 0x80
        first = fin | opcode
        mask_bit = 0x80
        length = len(payload)

        header = bytearray()
        header.append(first)
        if length < 126:
            header.append(mask_bit | length)
        elif length < 65536:
            header.append(mask_bit | 126)
            header.extend(ustruct.pack("!H", length))
        else:
            header.append(mask_bit | 127)
            header.extend(ustruct.pack("!Q", length))

        mask_key = uos.urandom(4)
        header.extend(mask_key)
        masked_payload = self._mask_bytes(payload, mask_key)
        self._write_all(self.sock, bytes(header))
        self._write_all(self.sock, masked_payload)

    def _mask_bytes(self, payload, mask_key):
        out = bytearray(len(payload))
        for i in range(len(payload)):
            out[i] = payload[i] ^ mask_key[i % 4]
        return bytes(out)

    def _read_exact(self, sock, size):
        if size == 0:
            return b""
        chunks = bytearray()
        while len(chunks) < size:
            try:
                chunk = self._sock_read(sock, size - len(chunks))
            except Exception as e:
                if self._is_timeout_error(e):
                    raise WsTimeout("socket timeout")
                raise
            if not chunk:
                if len(chunks) == 0:
                    return None
                return None
            chunks.extend(chunk)
        return bytes(chunks)

    def _sock_read(self, sock, size):
        if hasattr(sock, "read"):
            return sock.read(size)
        return sock.recv(size)

    def _write_all(self, sock, data):
        sent = 0
        total = len(data)
        while sent < total:
            if hasattr(sock, "write"):
                count = sock.write(data[sent:])
            else:
                count = sock.send(data[sent:])
            if count is None:
                count = 0
            if count <= 0:
                raise WsClosed("socket write failed")
            sent += count

    def _is_timeout_error(self, exc):
        text = str(exc)
        if "timed out" in text.lower():
            return True
        args = getattr(exc, "args", None)
        if not args:
            return False
        code = args[0]
        return code in (11, 110, 115, 116)
