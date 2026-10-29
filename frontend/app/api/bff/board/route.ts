// Stub (DEC-010).
export const GET = async (request: Request): Promise<Response> => {
  void request;
  return new Response(null, { status: 501 });
};
