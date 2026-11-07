import { checkCheckinCsrf, postCheckin, readFields, reply, TOKEN_SHAPE } from '@/lib/checkin/server';
import { isUkMobile } from '@/lib/forms/ukMobile';

// "Text me a code": one number. The answer is the same whoever's number it is (the back end never says who is on the roster).

type Context = { params: Promise<{ token: string }> };

export async function POST(request: Request, context: Context): Promise<Response> {
  const { token } = await context.params;
  if (!TOKEN_SHAPE.test(token) || !checkCheckinCsrf(request, token)) return reply(403, { state: 'forbidden' });
  const body = await readFields(request, ['mobile']);
  if (body === null || typeof body.mobile !== 'string' || !isUkMobile(body.mobile)) return reply(400, { state: 'invalid' });
  return postCheckin(request, token, 'code', { mobile: body.mobile });
}
