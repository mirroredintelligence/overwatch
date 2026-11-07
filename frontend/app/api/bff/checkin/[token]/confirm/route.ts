import { checkCheckinCsrf, postCheckin, readFields, reply, TOKEN_SHAPE } from '@/lib/checkin/server';
import { isUkMobile } from '@/lib/forms/ukMobile';

// The code typed, and the person goes on or off shift. `hours` is only for going on.

type Context = { params: Promise<{ token: string }> };

const CODE = /^[0-9 -]{4,12}$/;
const MAX_HOURS = 14;
const FIELDS = ['mobile', 'code', 'action', 'hours'] as const;

export async function POST(request: Request, context: Context): Promise<Response> {
  const { token } = await context.params;
  if (!TOKEN_SHAPE.test(token) || !checkCheckinCsrf(request, token)) return reply(403, { state: 'forbidden' });
  const body = await readFields(request, FIELDS);
  if (body === null) return reply(400, { state: 'invalid' });
  const { mobile, code, action, hours } = body;
  if (typeof mobile !== 'string' || !isUkMobile(mobile)) return reply(400, { state: 'invalid' });
  if (typeof code !== 'string' || !CODE.test(code)) return reply(400, { state: 'invalid' });
  if (action !== 'on' && action !== 'off') return reply(400, { state: 'invalid' });
  if (hours !== undefined && (typeof hours !== 'number' || !Number.isInteger(hours) || hours < 1 || hours > MAX_HOURS || action !== 'on')) {
    return reply(400, { state: 'invalid' });
  }
  return postCheckin(request, token, 'confirm', hours === undefined ? { mobile, code, action } : { mobile, code, action, hours });
}
