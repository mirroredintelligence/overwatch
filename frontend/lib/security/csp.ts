// The content security policy and the security headers of every response (S01).
//
// No third-party script, style, font or request is allowed: the policy names 'self' and a
// per-request nonce only. `strict-dynamic` lets the scripts Next.js loads with the nonce load their
// own chunks. unsafe-eval is allowed in development alone, because the dev server needs it.

// Base64 and URL-safe characters only. A nonce that could hold a quote, a semicolon or a space
// could end the header early, so it is refused rather than escaped.
const NONCE_PATTERN = /^[A-Za-z0-9+/=_-]+$/;

// A scheme and host (and port) only: no path, wildcard, quote, space or semicolon, so an origin can
// add one source to form-action and never another directive or another keyword.
const ORIGIN_PATTERN = /^https?:\/\/[A-Za-z0-9.-]+(:\d{1,5})?$/;

export interface CspOptions {
  // Extra places a form on this page may send its answer, after 'self'. The staff sign-in page
  // names the sign-in provider here: Chrome applies form-action to the redirect that answers the
  // form's post, so the redirect to the provider is blocked unless the page allows it (W09).
  formActionOrigins?: readonly string[];
}

export function buildCsp(nonce: string, dev: boolean, options: CspOptions = {}): string {
  if (!NONCE_PATTERN.test(nonce)) {
    throw new Error('the CSP nonce is not valid');
  }
  const formActions = ["'self'"];
  for (const origin of options.formActionOrigins ?? []) {
    if (!ORIGIN_PATTERN.test(origin)) {
      throw new Error('a form-action origin is not a scheme and host');
    }
    formActions.push(origin);
  }
  const scriptSources = ["'self'", `'nonce-${nonce}'`, "'strict-dynamic'"];
  if (dev) {
    scriptSources.push("'unsafe-eval'");
  }
  return [
    "default-src 'self'",
    `script-src ${scriptSources.join(' ')}`,
    `style-src 'self' 'nonce-${nonce}'`,
    "img-src 'self' data:",
    "font-src 'self'",
    "connect-src 'self'",
    "worker-src 'self'",
    "manifest-src 'self'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    `form-action ${formActions.join(' ')}`,
    "object-src 'none'",
    'upgrade-insecure-requests',
  ].join('; ');
}

export function securityHeaders(): Record<string, string> {
  return {
    'Strict-Transport-Security': 'max-age=63072000; includeSubDomains',
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'no-referrer',
    'Permissions-Policy': 'camera=(), microphone=(), geolocation=(), payment=()',
    'Cross-Origin-Opener-Policy': 'same-origin',
  };
}
