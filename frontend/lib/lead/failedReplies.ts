// The text replies the system could not take in (DEC-1359). The back end lists them for the shift lead; the screen
// says what went wrong in plain words and never shows a phone number (the back end holds only a hash).

export type FailedReply = {
  sid: string;
  receivedAt: string;
  text: string;
  senderName: string | null;
  /** What could not be done, in words for a lead. */
  problem: string;
};

const PROBLEMS: Record<string, string> = {
  'find-sender': 'We could not look up the sender.',
  'replay-marker': 'We could not note it as seen.',
  enqueue: 'We could not queue it.',
};

export function problemWords(step: string): string {
  return PROBLEMS[step] ?? 'We could not take it in.';
}

/** The replies of the back end's answer. An entry that is not one (no id, no time) is dropped, never guessed at. */
export function failedRepliesFrom(data: unknown): FailedReply[] {
  const list = (data as { replies?: unknown } | undefined)?.replies;
  if (!Array.isArray(list)) throw new Error('not the failed replies answer');
  const out: FailedReply[] = [];
  for (const item of list) {
    const reply = item as Record<string, unknown> | null;
    if (typeof reply?.sid !== 'string' || typeof reply.receivedAt !== 'string' || typeof reply.step !== 'string') continue;
    out.push({
      sid: reply.sid,
      receivedAt: reply.receivedAt,
      text: typeof reply.text === 'string' ? reply.text : '',
      senderName: typeof reply.senderName === 'string' ? reply.senderName : null,
      problem: problemWords(reply.step),
    });
  }
  return out;
}
