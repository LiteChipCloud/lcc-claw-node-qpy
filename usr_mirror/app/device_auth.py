import utime

from app.json_codec import dumps, loads

try:
    import request
except Exception:
    request = None


def _string(value):
    if value is None:
        return ""
    return str(value)


def _int(value, default_value):
    try:
        return int(value)
    except Exception:
        return default_value


def _normalize_scopes(value):
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item)]
    return []


def _epoch_ms_fallback():
    try:
        return int(utime.time() * 1000)
    except Exception:
        return 0


def _auth_block(cfg, state):
    explicit_token = _string(getattr(cfg, "OPENCLAW_AUTH_TOKEN", "")).strip()
    cached_device_token = _string(getattr(state, "device_token", "")).strip()
    auth = {}
    if explicit_token:
        auth["token"] = explicit_token
        if cached_device_token:
            auth["deviceToken"] = cached_device_token
    elif cached_device_token:
        auth["token"] = cached_device_token
        auth["deviceToken"] = cached_device_token
    if auth:
        return auth, explicit_token or cached_device_token
    return None, ""


def _remote_signer_headers(cfg):
    headers = {
        "Content-Type": "application/json",
    }
    token = _string(getattr(cfg, "REMOTE_SIGNER_HTTP_AUTH_TOKEN", "")).strip()
    if token:
        headers["Authorization"] = "Bearer " + token
    extra = getattr(cfg, "REMOTE_SIGNER_HTTP_HEADERS", None)
    if isinstance(extra, dict):
        for key in extra:
            headers[str(key)] = str(extra[key])
    return headers


def _response_json(resp):
    json_fn = getattr(resp, "json", None)
    if json_fn:
        try:
            data = json_fn()
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    text = getattr(resp, "text", "")
    if isinstance(text, (list, tuple)):
        text = "".join([str(item) for item in text])
    elif not isinstance(text, str):
        try:
            chunks = []
            for item in text:
                chunks.append(str(item))
            text = "".join(chunks)
        except Exception:
            text = str(text)
    return loads(text)


def _request_remote_signature(cfg, state, auth_token, nonce):
    if request is None:
        raise Exception("request module unavailable")

    url = _string(getattr(cfg, "REMOTE_SIGNER_HTTP_URL", "")).strip()
    if not url:
        raise Exception("remote signer url missing")

    payload = {
        "logicalDeviceId": _string(getattr(cfg, "DEVICE_ID", "")).strip(),
        "deviceName": _string(getattr(cfg, "DEVICE_NAME", "")).strip(),
        "clientId": _string(getattr(cfg, "OPENCLAW_CLIENT_ID", "node-host")).strip(),
        "clientMode": _string(getattr(cfg, "OPENCLAW_CLIENT_MODE", "node")).strip(),
        "role": _string(getattr(cfg, "OPENCLAW_ROLE", "node")).strip(),
        "scopes": _normalize_scopes(getattr(cfg, "OPENCLAW_SCOPES", [])),
        "token": auth_token,
        "nonce": nonce,
        "platform": _string(getattr(cfg, "OPENCLAW_CLIENT_PLATFORM", "quectel")).strip(),
        "deviceFamily": _string(getattr(cfg, "OPENCLAW_CLIENT_DEVICE_FAMILY", "quecpython")).strip(),
        "requestedAtMs": _epoch_ms_fallback(),
    }
    resp = None
    try:
        body_text = dumps(payload)
        headers = _remote_signer_headers(cfg)
        try:
            resp = request.post(url, data=body_text, headers=headers)
        except TypeError as e:
            if "buffer protocol" not in str(e):
                raise
            resp = request.post(url, data=body_text.encode("utf-8"), headers=headers)
        status_code = getattr(resp, "status_code", 0)
        if status_code != 200:
            raise Exception("remote signer http %s" % str(status_code))
        body = _response_json(resp)
        device = body.get("device") if isinstance(body, dict) else None
        if not isinstance(device, dict):
            raise Exception("remote signer invalid payload")
        if not device.get("nonce"):
            device["nonce"] = nonce
        state.last_signer = {
            "url": url,
            "signed_at": device.get("signedAt"),
            "logical_device_id": payload["logicalDeviceId"],
        }
        return device
    finally:
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass


def resolve_connect_security(cfg, state, nonce):
    auth, auth_token = _auth_block(cfg, state)
    device = None
    device_auth_mode = _string(getattr(cfg, "OPENCLAW_DEVICE_AUTH_MODE", "none")).strip() or "none"
    if device_auth_mode == "remote_signer_http":
        device = _request_remote_signature(cfg, state, auth_token, nonce)
    elif device_auth_mode != "none":
        raise Exception("unsupported device auth mode: %s" % device_auth_mode)
    return auth, device, device_auth_mode
