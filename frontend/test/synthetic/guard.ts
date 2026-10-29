/**
 * The guard for the synthetic checks (O09). The checks run against a deployed test environment,
 * so they touch only a host that is named in SYNTHETIC_ALLOWED_HOSTS, and only over https (plain
 * http is allowed for localhost, for the compose stack). Anything else skips with a reason, and no
 * reason ever contains a secret.
 *
 * Environment (values come from the environment or the CI secrets, never from the code):
 * - SYNTHETIC_BASE_URL: the front end under test.
 * - SYNTHETIC_BACKEND_URL: the back end's test hook is served here.
 * - SYNTHETIC_ALLOWED_HOSTS: comma-separated host names (with a port when the URL has one).
 * - SYNTHETIC_HOOK_TOKEN: the bearer token for POST /test/synthetic/prompt.
 */

export type SyntheticTarget =
  | { ok: true; baseUrl: string; backendUrl: string; hookToken: string }
  | { ok: false; reason: string };

export type SyntheticEnv = Readonly<Record<string, string | undefined>>;

const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1']);

function skip(reason: string): SyntheticTarget {
  return { ok: false, reason };
}

function allowedHosts(raw: string | undefined): Set<string> {
  return new Set(
    (raw ?? '')
      .split(',')
      .map((host) => host.trim().toLowerCase())
      .filter((host) => host.length > 0),
  );
}

/** A URL that the checks may use: https, or http to a local host. Returns null otherwise. */
function parseTarget(raw: string): URL | null {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return null;
  }
  const secure = url.protocol === 'https:';
  const local = url.protocol === 'http:' && LOCAL_HOSTS.has(url.hostname);
  return secure || local ? url : null;
}

export function syntheticTarget(env: SyntheticEnv): SyntheticTarget {
  const base = env.SYNTHETIC_BASE_URL?.trim();
  if (!base) return skip('SYNTHETIC_BASE_URL is not set, so the synthetic checks are skipped.');
  const baseUrl = parseTarget(base);
  if (!baseUrl) {
    return skip('SYNTHETIC_BASE_URL must be an https URL (http only for localhost).');
  }

  const hosts = allowedHosts(env.SYNTHETIC_ALLOWED_HOSTS);
  if (!hosts.has(baseUrl.host)) {
    return skip(
      `SYNTHETIC_BASE_URL host "${baseUrl.host}" is not in SYNTHETIC_ALLOWED_HOSTS, ` +
        'so the synthetic checks are skipped. Never run them against production by accident.',
    );
  }

  const backend = env.SYNTHETIC_BACKEND_URL?.trim();
  if (!backend) return skip('SYNTHETIC_BACKEND_URL is not set, so the synthetic checks are skipped.');
  const backendUrl = parseTarget(backend);
  if (!backendUrl) {
    return skip('SYNTHETIC_BACKEND_URL must be an https URL (http only for localhost).');
  }
  if (!hosts.has(backendUrl.host)) {
    return skip(
      `SYNTHETIC_BACKEND_URL host "${backendUrl.host}" is not in SYNTHETIC_ALLOWED_HOSTS, ` +
        'so the synthetic checks are skipped.',
    );
  }

  const hookToken = env.SYNTHETIC_HOOK_TOKEN ?? '';
  if (!hookToken) return skip('SYNTHETIC_HOOK_TOKEN is not set, so the synthetic checks are skipped.');

  return {
    ok: true,
    baseUrl: baseUrl.origin,
    backendUrl: backendUrl.origin,
    hookToken,
  };
}

/** True when a link the hook returned is on the same origin as the target: the checks never
 * open a link that leads anywhere else. */
export function sameOrigin(link: string, baseUrl: string): boolean {
  try {
    return new URL(link).origin === new URL(baseUrl).origin;
  } catch {
    return false;
  }
}
