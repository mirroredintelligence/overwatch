// The web server's clock, in one place (a Server Component may not call Date.now
// itself under the React purity rules).
export function serverNow(): number {
  return Date.now();
}
