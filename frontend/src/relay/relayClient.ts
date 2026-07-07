// Client for the on-prem GP relay (http://localhost:7321 on the same workstation).
//
// The browser hop to the loopback relay is gated by Chrome Local Network Access from Chrome 142+:
// every fetch sets `targetAddressSpace: "loopback"` (relaxes the https->http loopback mixed-content
// block and requests the LNA permission). The bearer is fetched at runtime from the backend
// (relayCredential) - it's never baked into the build.

import client from '../apollo';
import { GET_RELAY_CREDENTIAL } from '../graphql/queries';

// The relay always binds 127.0.0.1:7321 on the same machine. Overridable for non-default setups.
const RELAY_BASE = import.meta.env.VITE_RELAY_URL || 'http://localhost:7321';

// `targetAddressSpace` (Chrome LNA) isn't in the standard DOM lib types yet.
type LoopbackRequestInit = RequestInit & { targetAddressSpace?: 'loopback' | 'local' | 'public' };

export class RelayError extends Error {
  code: string;
  constructor(message: string, code = 'relay_error') {
    super(message);
    this.name = 'RelayError';
    this.code = code;
  }
}

export interface RelayVendor {
  vendor_id: string;
  vendor_name: string;
  vendor_class: string | null;
  status: number;
}

export interface RelayHealth {
  ok: boolean;
  version?: string;
}

export type LoopbackPermission = PermissionState | 'unsupported';

let cachedSecret: string | null = null;

export function resetRelaySecretCache(): void {
  cachedSecret = null;
}

async function getSecret(): Promise<string> {
  if (cachedSecret) return cachedSecret;
  const res = await client.query<{ relayCredential: { secret: string } }>({
    query: GET_RELAY_CREDENTIAL,
    fetchPolicy: 'no-cache',
  });
  const secret = res.data?.relayCredential?.secret;
  if (!secret) throw new RelayError('no relay credential available for this user', 'no_credential');
  cachedSecret = secret;
  return secret;
}


function extractError(body: unknown, status: number): RelayError {
  const detail = (body as { detail?: unknown })?.detail;
  if (typeof detail === 'string') return new RelayError(detail);
  if (Array.isArray(detail)) {
    // FastAPI 422 validation errors
    const msg = detail
      .map((d) => (d as { msg?: string }).msg)
      .filter(Boolean)
      .join('; ');
    return new RelayError(msg || `relay request failed (${status})`, 'validation_error');
  }
  if (detail && typeof detail === 'object') {
    const d = detail as { error?: string; message?: string; error_description?: string };
    return new RelayError(
      d.message || d.error_description || d.error || `relay request failed (${status})`,
      d.error || 'relay_error',
    );
  }
  return new RelayError(`relay request failed (${status})`);
}

async function relayFetch(path: string, init: LoopbackRequestInit = {}, auth = true): Promise<Response> {
  const headers = new Headers(init.headers);
  if (auth) headers.set('Authorization', `Bearer ${await getSecret()}`);
  const reqInit: LoopbackRequestInit = { ...init, headers, targetAddressSpace: 'loopback' };
  try {
    return await fetch(`${RELAY_BASE}${path}`, reqInit as RequestInit);
  } catch (e) {
    throw new RelayError(`GP relay not reachable at ${RELAY_BASE}: ${(e as Error).message}`, 'relay_unreachable');
  }
}

export async function checkRelayHealth(): Promise<RelayHealth> {
  try {
    const r = await relayFetch('/health', {}, false);
    if (!r.ok) return { ok: false };
    const body = (await r.json()) as { status?: string; version?: string };
    return { ok: body.status === 'ok', version: body.version };
  } catch {
    return { ok: false };
  }
}

export async function getRelayVendors(company: string): Promise<RelayVendor[]> {
  const r = await relayFetch(`/vendors?company=${encodeURIComponent(company)}`);
  const body = await r.json();
  if (!r.ok) throw extractError(body, r.status);
  return (body as { vendors: RelayVendor[] }).vendors;
}

export interface RelayPoLine {
  item_number: string;
  item_description: string;
  quantity: number;
  unit_cost: number;
  location_code?: string;
  uofm?: string;
  product_indicator: number; // 1 non-inv, 2 job cost
  job_number?: string | null;
  cost_code?: string | null; // 'phase-step-element' e.g. '210-200-2'
}

export interface RelayPoRequest {
  company: string;
  header: { vendor_id: string; buyer_id: string; confirm_with: string; doc_date: string };
  lines: RelayPoLine[];
}

export interface RelayPoResponse {
  po_number: string;
  company: string;
  lines_created: number;
  subtotal: string;
  doc_date: string;
  vendor_id: string;
}

export async function postRelayPo(req: RelayPoRequest): Promise<RelayPoResponse> {
  const r = await relayFetch('/po', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  const body = await r.json();
  if (!r.ok) throw extractError(body, r.status);
  return body as RelayPoResponse;
}

export interface RelayReceiptLine {
  po_line_ord: number; // GP POP10110.ORD of the PO line being received (16384, 32768, ...)
  quantity: number;
  rack_location: string; // where the goods were physically shelved (aisle-bay-bin); required non-empty
  revision_number?: string | null;
  comments?: string | null;
}

export interface RelayReceiptRequest {
  company: string;
  po_number: string;
  lines: RelayReceiptLine[];
  batch_prefix?: string;
  receipt_date?: string; // yyyy-mm-dd; defaults to today on the relay
  received_by?: string | null;
}

export interface RelayReceiptResponse {
  receipt_number: string;
  batch_number: string;
  po_number: string;
  company: string;
  lines_received: number;
  custom_db_written: boolean;
}

// Post a GP receipt against a PO. The relay enforces remaining quantity and surfaces
// qty_exceeds_remaining / line_not_receivable / po_line_not_found / po_not_found, which extractError
// maps to RelayError.code + a human-readable message.
export async function postRelayReceipt(req: RelayReceiptRequest): Promise<RelayReceiptResponse> {
  const r = await relayFetch('/receipt', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  const body = await r.json();
  if (!r.ok) throw extractError(body, r.status);
  return body as RelayReceiptResponse;
}

export async function getLoopbackPermissionState(): Promise<LoopbackPermission> {
  try {
    const permissions = navigator.permissions as unknown as {
      query: (d: { name: string }) => Promise<PermissionStatus>;
    };
    const status = await permissions.query({ name: 'loopback-network' });
    return status.state;
  } catch {
    return 'unsupported';
  }
}
