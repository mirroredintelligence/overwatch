// The answer a BFF route gives for a read or write the back end does not offer yet. It never stands in
// for data: a page that gets it shows that the page could not be loaded, not an empty list (H-330).

export function notBuilt(): Response {
  return Response.json(
    { code: 'not-built', message: 'This is not available yet.' },
    { status: 501, headers: { 'Cache-Control': 'no-store' } },
  );
}
