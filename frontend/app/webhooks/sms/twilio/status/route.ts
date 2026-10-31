import { forwardTwilioWebhook, notFound } from '@/lib/webhooks/forward';

// POST /webhooks/sms/twilio/status: a delivery receipt (DEC-1302). The public path Twilio calls; the forward
// passes it to the back end, which checks the signature. Every other method is an empty 404.
export const dynamic = 'force-dynamic';

export function POST(request: Request): Promise<Response> {
  return forwardTwilioWebhook(request, 'status');
}

export { notFound as GET, notFound as PUT, notFound as PATCH, notFound as DELETE, notFound as HEAD, notFound as OPTIONS };
