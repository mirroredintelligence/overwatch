import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // `next dev` adds its own grey badge to every page, which sits over the app's header. It is dev-only (a production
  // build never has it) and the error overlay is unaffected.
  devIndicators: false,
};

export default nextConfig;
