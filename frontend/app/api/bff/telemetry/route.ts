// Browser telemetry ingest (O02). Stub for the red commit: accepts and discards.

export async function POST(request: Request): Promise<Response> {
  void request;
  return new Response(null, { status: 204 });
}
