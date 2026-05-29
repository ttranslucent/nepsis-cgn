# Packet Provenance

NepsisCGN records packet provenance as an additive sidecar ledger. The ledger is
separate from session replay state so it can describe evidence without claiming
that existing session storage is immutable.

## Scope

The v1 subsystem records packet observations for backend packet-producing paths:

- retained payload records for backend MVP packets, runtime iteration packets,
  ambient operator audit packets, abandoned-loop packets, and stage-audit gate
  packets
- hash-only records for stateless operator-packet responses and MCP tool
  results

Public `/mvp` and `/v1/mvp` packet shapes are unchanged. Provenance is recorded
beside the packet and is not inserted into the deterministic MVP payload.

## Hashing

Payload hashes use SHA256 over canonical JSON:

- object keys are sorted
- JSON separators are compact
- UTF-8 bytes are hashed

The recorded value is stored as `sha256:<hex-digest>`.

## Retention Modes

`retained` records include a `payload` copy and can be rehashed directly during
audit export.

`hash_only` records include identity, request context, lineage fields, and
`payload_hash`, but do not retain the packet body. This is the default for
stateless operator-packet and MCP paths to preserve the current no-body server
retention posture.

## Storage

By default the JSONL ledger is written to:

```text
ledger/sessions/packet_provenance.jsonl
```

Override the path with:

```text
NEPSIS_PACKET_PROVENANCE_PATH=/absolute/path/to/packet_provenance.jsonl
```

Disable recording with:

```text
NEPSIS_PACKET_PROVENANCE_ENABLED=false
```

Writes are append-only. Re-appending the exact same record is idempotent. A
record with the same packet ID and a different payload hash is treated as an
integrity conflict.

## Signing

Unsigned mode is the default. It still verifies retained payload hashes.

Enable HMAC-SHA256 signing with:

```text
NEPSIS_PACKET_SIGNING_SECRET=<secret>
NEPSIS_PACKET_SIGNING_KEY_ID=<key-id>
```

The signing input excludes the `signature` and `integrity` fields so signatures
can be verified after those fields are attached. v1 does not include KMS,
public-key signatures, or key rotation beyond the recorded key ID.

## Request Context

Records can capture:

- request ID
- HTTP method or MCP method marker
- route path
- sequence within the request
- session ID
- parent packet ID
- source surface

Owner IDs are not stored directly. When available, provenance records store an
owner hash.

## Read APIs

Session-scoped provenance:

```text
GET /v1/sessions/{session_id}/provenance
```

Request reconstruction:

```text
GET /v1/provenance/requests/{request_id}
```

Packet lineage:

```text
GET /v1/provenance/packets/{packet_id}/lineage
```

Verification-ready audit export:

```text
GET /v1/sessions/{session_id}/audit-export
```

Session endpoints use the same owner checks as other engine session controls.
They are not public MVP endpoints.

## Audit Export

Audit exports include:

- session summary
- current session packet list
- provenance records
- nodes and edges for visualization
- retained-payload hash verification failures
- signature verification failures
- hash-only omissions

Historical sessions do not gain request-level provenance retroactively.
Provenance starts when this subsystem is enabled and packet observations are
recorded.
