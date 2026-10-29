// The content security policy and the security headers of every response (S01).
//
// No third-party script, style, font or request is allowed: the policy names 'self' and a
// per-request nonce only. `strict-dynamic` lets the scripts Next.js loads with the nonce load their
// own chunks. unsafe-eval is allowed in development alone, because the dev server needs it.

// Base64 and URL-safe characters only. A nonce that could hold a quote, a semicolon or a space
// could end the header early, so it is refused rather than escaped.
const NONCE_PATTERN = /^[A-Za-z0-9+/=_-]+$/;

export function buildCsp(nonce: string, dev: boolean): string {
  if (!NONCE_PATTERN.test(nonce)) {
    throw new Error('the CSP nonce is not valid');
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
    "form-action 'self'",
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
