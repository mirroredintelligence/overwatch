// Push subscription in the browser (W34). Called only after the reporter has pressed Allow and the
// browser has granted permission. The subscription goes to the BFF, never to a log or to storage.

export type PushSubscriptionShape = {
  endpoint: string;
  keys: { p256dh: string; auth: string };
};

function base64UrlToBytes(value: string): Uint8Array<ArrayBuffer> {
  const padded = value.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(value.length / 4) * 4, '=');
  const raw = atob(padded);
  const bytes = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i);
  return bytes;
}

export async function subscribeToPush(
  registration: ServiceWorkerRegistration,
  publicKey: string,
): Promise<PushSubscriptionShape> {
  const subscription = await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: base64UrlToBytes(publicKey),
  });
  const json = subscription.toJSON();
  if (!json.endpoint || !json.keys?.p256dh || !json.keys?.auth) {
    throw new Error('The browser gave an incomplete push subscription.');
  }
  return { endpoint: json.endpoint, keys: { p256dh: json.keys.p256dh, auth: json.keys.auth } };
}
