#!/usr/bin/env node

import http from "node:http";

function argValue(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : null;
}

const port = Number(argValue("--port") ?? process.env.PORT ?? 3102);
const records = new Map();

function normalizeEmail(value) {
  return typeof value === "string" ? value.trim().toLowerCase() : "";
}

function recordFor(email) {
  const normalized = normalizeEmail(email);
  if (!records.has(normalized)) {
    records.set(normalized, {
      email: normalized,
      newestCode: null,
      sends: [],
      verifications: [],
    });
  }
  return records.get(normalized);
}

function json(res, status, body) {
  res.writeHead(status, {
    "Content-Type": "application/json",
    "X-Supabase-Api-Version": "2024-01-01",
  });
  res.end(JSON.stringify(body));
}

async function jsonBody(req) {
  const chunks = [];
  for await (const chunk of req) {
    chunks.push(chunk);
  }
  const raw = Buffer.concat(chunks).toString("utf-8");
  return raw ? JSON.parse(raw) : {};
}

function publicState(email) {
  const record = recordFor(email);
  return {
    email: record.email,
    newestCode: record.newestCode,
    sendCount: record.sends.length,
    verifyCount: record.verifications.length,
    sends: record.sends,
    verifications: record.verifications,
  };
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url ?? "/", `http://${req.headers.host ?? `127.0.0.1:${port}`}`);

  try {
    if (req.method === "GET" && url.pathname === "/health") {
      json(res, 200, { ok: true });
      return;
    }

    if (req.method === "POST" && url.pathname === "/_test/reset") {
      records.clear();
      json(res, 200, { ok: true });
      return;
    }

    if (req.method === "GET" && url.pathname === "/_test/otp") {
      json(res, 200, publicState(url.searchParams.get("email") ?? ""));
      return;
    }

    if (req.method === "POST" && url.pathname === "/auth/v1/otp") {
      const body = await jsonBody(req);
      const email = normalizeEmail(body.email);
      if (!email) {
        json(res, 400, { message: "email required", code: "validation_failed" });
        return;
      }

      const record = recordFor(email);
      const code = String(420001 + record.sends.length).padStart(6, "0");
      record.newestCode = code;
      record.sends.push({
        at: new Date().toISOString(),
        code,
        body,
      });
      json(res, 200, {});
      return;
    }

    if (req.method === "POST" && url.pathname === "/auth/v1/verify") {
      const body = await jsonBody(req);
      const email = normalizeEmail(body.email);
      const token = typeof body.token === "string" ? body.token.trim() : "";
      const record = recordFor(email);
      record.verifications.push({
        at: new Date().toISOString(),
        token,
        body,
      });

      if (email && token && token === record.newestCode) {
        json(res, 200, {
          user: {
            id: `stub-${email}`,
            email,
            aud: "authenticated",
            role: "authenticated",
          },
        });
        return;
      }

      json(res, 403, {
        message: "Token has expired or is invalid",
        code: "otp_expired",
        error_code: "otp_expired",
      });
      return;
    }

    json(res, 404, { message: "not found" });
  } catch (error) {
    json(res, 500, { message: error instanceof Error ? error.message : "unknown error" });
  }
});

server.listen(port, "127.0.0.1", () => {
  console.log(`fake Supabase OTP server listening on http://127.0.0.1:${port}`);
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => {
    server.close(() => process.exit(0));
  });
}
