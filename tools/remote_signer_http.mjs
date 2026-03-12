#!/usr/bin/env node
import crypto from "node:crypto";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const bind = process.env.REMOTE_SIGNER_BIND || "0.0.0.0";
const port = Number.parseInt(process.env.REMOTE_SIGNER_PORT || "8787", 10);
const authToken = (process.env.REMOTE_SIGNER_AUTH_TOKEN || "").trim();
const identityDir = process.env.REMOTE_SIGNER_IDENTITY_DIR || path.join(os.homedir(), ".lcc-claw-node-qpy", "remote-signer", "identities");
const defaultLogicalId = process.env.REMOTE_SIGNER_DEFAULT_LOGICAL_ID || "default";
const ED25519_SPKI_PREFIX = Buffer.from("302a300506032b6570032100", "hex");

function base64UrlEncode(buf) {
  return buf.toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function sanitizeLogicalId(raw) {
  const value = String(raw || defaultLogicalId).trim() || defaultLogicalId;
  return value.replace(/[^a-zA-Z0-9._-]+/g, "-").replace(/^-+|-+$/g, "") || defaultLogicalId;
}

function derivePublicKeyRaw(publicKeyPem) {
  const key = crypto.createPublicKey(publicKeyPem);
  const spki = key.export({ type: "spki", format: "der" });
  if (spki.length === ED25519_SPKI_PREFIX.length + 32 && spki.subarray(0, ED25519_SPKI_PREFIX.length).equals(ED25519_SPKI_PREFIX)) {
    return spki.subarray(ED25519_SPKI_PREFIX.length);
  }
  return spki;
}

function deriveDeviceIdFromPem(publicKeyPem) {
  return crypto.createHash("sha256").update(derivePublicKeyRaw(publicKeyPem)).digest("hex");
}

function publicKeyRawBase64UrlFromPem(publicKeyPem) {
  return base64UrlEncode(derivePublicKeyRaw(publicKeyPem));
}

function buildDeviceAuthPayloadV3(params) {
  const scopes = Array.isArray(params.scopes) ? params.scopes.join(",") : "";
  const token = params.token || "";
  const platform = String(params.platform || "").trim().toLowerCase();
  const deviceFamily = String(params.deviceFamily || "").trim().toLowerCase();
  return [
    "v3",
    params.deviceId,
    params.clientId,
    params.clientMode,
    params.role,
    scopes,
    String(params.signedAtMs),
    token,
    params.nonce,
    platform,
    deviceFamily,
  ].join("|");
}

function signPayload(privateKeyPem, payload) {
  const key = crypto.createPrivateKey(privateKeyPem);
  return base64UrlEncode(crypto.sign(null, Buffer.from(payload, "utf8"), key));
}

function identityPath(logicalId) {
  return path.join(identityDir, `${logicalId}.json`);
}

function loadOrCreateIdentity(logicalId) {
  const file = identityPath(logicalId);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  if (fs.existsSync(file)) {
    const parsed = JSON.parse(fs.readFileSync(file, "utf8"));
    if (parsed?.publicKeyPem && parsed?.privateKeyPem) {
      const deviceId = deriveDeviceIdFromPem(parsed.publicKeyPem);
      if (parsed.deviceId !== deviceId) {
        parsed.deviceId = deviceId;
        fs.writeFileSync(file, `${JSON.stringify(parsed, null, 2)}\n`, { mode: 0o600 });
      }
      return parsed;
    }
  }
  const { publicKey, privateKey } = crypto.generateKeyPairSync("ed25519");
  const publicKeyPem = publicKey.export({ type: "spki", format: "pem" }).toString();
  const privateKeyPem = privateKey.export({ type: "pkcs8", format: "pem" }).toString();
  const identity = {
    version: 1,
    logicalId,
    deviceId: deriveDeviceIdFromPem(publicKeyPem),
    publicKeyPem,
    privateKeyPem,
    createdAtMs: Date.now(),
  };
  fs.writeFileSync(file, `${JSON.stringify(identity, null, 2)}\n`, { mode: 0o600 });
  fs.chmodSync(file, 0o600);
  return identity;
}

function unauthorized(res) {
  res.writeHead(401, { "Content-Type": "application/json" });
  res.end(JSON.stringify({ ok: false, error: "unauthorized" }));
}

function badRequest(res, message) {
  res.writeHead(400, { "Content-Type": "application/json" });
  res.end(JSON.stringify({ ok: false, error: message }));
}

function jsonResponse(res, statusCode, body) {
  res.writeHead(statusCode, { "Content-Type": "application/json" });
  res.end(JSON.stringify(body));
}

function requireAuth(req, res) {
  if (!authToken) {
    return true;
  }
  const header = String(req.headers.authorization || "").trim();
  if (header === `Bearer ${authToken}`) {
    return true;
  }
  unauthorized(res);
  return false;
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => {
      try {
        const raw = Buffer.concat(chunks).toString("utf8");
        resolve(raw ? JSON.parse(raw) : {});
      } catch (error) {
        reject(error);
      }
    });
    req.on("error", reject);
  });
}

const server = http.createServer(async (req, res) => {
  if (req.url === "/health" && req.method === "GET") {
    return jsonResponse(res, 200, { ok: true, bind, port });
  }
  if (req.url?.startsWith("/identity") && req.method === "GET") {
    if (!requireAuth(req, res)) {
      return;
    }
    const url = new URL(req.url, `http://${req.headers.host || "127.0.0.1"}`);
    const logicalId = sanitizeLogicalId(url.searchParams.get("logicalDeviceId"));
    const identity = loadOrCreateIdentity(logicalId);
    return jsonResponse(res, 200, {
      ok: true,
      logicalDeviceId: logicalId,
      deviceId: identity.deviceId,
      publicKey: publicKeyRawBase64UrlFromPem(identity.publicKeyPem),
    });
  }
  if (req.url === "/sign" && req.method === "POST") {
    if (!requireAuth(req, res)) {
      return;
    }
    let body;
    try {
      body = await readBody(req);
    } catch {
      return badRequest(res, "invalid json body");
    }
    const logicalId = sanitizeLogicalId(body.logicalDeviceId || body.deviceId || defaultLogicalId);
    const nonce = String(body.nonce || "").trim();
    const clientId = String(body.clientId || "node-host").trim();
    const clientMode = String(body.clientMode || "node").trim();
    const role = String(body.role || "node").trim();
    const scopes = Array.isArray(body.scopes) ? body.scopes.map((item) => String(item)) : [];
    const token = body.token ? String(body.token) : "";
    if (!nonce) {
      return badRequest(res, "nonce required");
    }
    const identity = loadOrCreateIdentity(logicalId);
    if (body.deviceId && String(body.deviceId).trim() && String(body.deviceId).trim() !== identity.deviceId) {
      return badRequest(res, "deviceId mismatch for logical device");
    }
    const signedAtMs = Number.isFinite(Number(body.signedAtMs)) ? Number(body.signedAtMs) : Date.now();
    const payload = buildDeviceAuthPayloadV3({
      deviceId: identity.deviceId,
      clientId,
      clientMode,
      role,
      scopes,
      signedAtMs,
      token,
      nonce,
      platform: body.platform,
      deviceFamily: body.deviceFamily,
    });
    const signature = signPayload(identity.privateKeyPem, payload);
    return jsonResponse(res, 200, {
      ok: true,
      logicalDeviceId: logicalId,
      payloadVersion: "v3",
      device: {
        id: identity.deviceId,
        publicKey: publicKeyRawBase64UrlFromPem(identity.publicKeyPem),
        signature,
        signedAt: signedAtMs,
        nonce,
      },
    });
  }
  jsonResponse(res, 404, { ok: false, error: "not found" });
});

server.listen(port, bind, () => {
  process.stdout.write(`remote signer listening on http://${bind}:${port}\n`);
});
