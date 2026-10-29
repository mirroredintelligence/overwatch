import type { IncomingMessage, ServerResponse } from 'node:http';
import { linkAnswerReply, linkRenewReply, linkViewReply, type LinkReplyFor } from '@/test/fixtures/links';

// The capacity link routes of the stand-in back end, for the browser tests (L01, DEC-167). The
// answers come from the same scenario table as the unit tests (test/fixtures/links.ts).

function send(response: ServerResponse, reply: LinkReplyFor) {
  response.writeHead(reply.status, {
    'Content-Type': 'application/json',
    'Cache-Control': 'no-store',
    ...reply.headers,
  });
  response.end(JSON.stringify(reply.body));
}

function readJson(request: IncomingMessage): Promise<Record<string, unknown>> {
  return new Promise((resolve) => {
    let text = '';
    request.on('data', (chunk: Buffer) => (text += chunk.toString()));
    request.on('end', () => {
      try {
        const parsed = JSON.parse(text) as unknown;
        resolve(typeof parsed === 'object' && parsed !== null ? (parsed as Record<string, unknown>) : {});
      } catch {
        resolve({});
      }
    });
  });
}

/** Answers `/links/{token}`, `/links/{token}/renew` and returns true; false for any other path. */
export async function handleLinkRoute(
  request: IncomingMessage,
  response: ServerResponse,
  pathname: string,
): Promise<boolean> {
  const match = /^\/links\/([^/]+)(\/renew)?$/.exec(pathname);
  if (match === null) return false;
  const token = decodeURIComponent(match[1] ?? '');
  if (request.method === 'GET' && match[2] === undefined) {
    send(response, linkViewReply(token));
  } else if (request.method === 'POST' && match[2] !== undefined) {
    send(response, linkRenewReply(token));
  } else if (request.method === 'POST') {
    const given = request.headers['x-csrf-token'];
    send(response, linkAnswerReply(token, typeof given === 'string' ? given : null, await readJson(request)));
  } else {
    response.writeHead(405).end();
  }
  return true;
}
