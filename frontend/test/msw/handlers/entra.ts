import { http, HttpResponse, type RequestHandler } from 'msw';
import type { FakeEntra } from '@/test/oidc/fake-entra';

// The two endpoints the sign-in's server calls: the token endpoint and the keys.
// The authorize endpoint is a browser redirect, so a test makes it by calling
// `fake.authorize(...)` with the address the sign-in redirected to.
// Not in the default handlers: a test builds a fake of its own and adds these.

export function entraHandlers(fake: FakeEntra): RequestHandler[] {
  const { host } = fake.options;
  return [
    http.post(`${host}/:directory/oauth2/v2.0/token`, async ({ request, params }) => {
      const form = new URLSearchParams(await request.text());
      const result = await fake.token(String(params.directory), form);
      return HttpResponse.json(result.body, { status: result.status });
    }),
    http.get(`${host}/:directory/discovery/v2.0/keys`, ({ params }) => {
      const result = fake.keys(String(params.directory));
      return HttpResponse.json(result.body, { status: result.status });
    }),
  ];
}
