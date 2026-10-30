// Red-commit stub (DEC-010).
export const GET = async (request: Request, context: { params: Promise<{ id: string }> }): Promise<Response> => {
  void request;
  void context;
  return new Response(null, { status: 501 });
};
