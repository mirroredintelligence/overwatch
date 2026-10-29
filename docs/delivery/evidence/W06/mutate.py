import subprocess, sys, pathlib, json

ROOT = pathlib.Path('/home/user/overwatch-wt/W06/frontend')
OUT = pathlib.Path('/tmp/claude-0/-home-user-overwatch/70fa8028-4332-5d32-abc2-645cf38440f5/scratchpad/w06-wall-live/w06-mutants-rerun.txt')

PARSE = 'lib/board/parse.ts'
BJ = 'lib/board/boardJson.ts'
LV = 'lib/board/liveness.ts'
HK = 'lib/board/useBoardFeed.ts'
EV = 'lib/bff/events.ts'
RT = 'app/api/bff/events/route.ts'
FC = 'lib/fhir/client.ts'
TL = 'components/board/Tile.tsx'
BD = 'components/board/Board.tsx'
BN = 'components/board/LastKnownBanner.tsx'
LB = 'components/board/LiveBoard.tsx'
CL = 'lib/board/client.ts'

T_PARSE = ['lib/board/parse.test.ts']
T_BJ = ['lib/board/boardJson.test.ts', 'lib/board/client.test.ts']
T_LV = ['lib/board/liveness.test.ts']
T_HK = ['lib/board/useBoardFeed.test.tsx', 'components/board/LiveBoard.test.tsx']
T_EV = ['lib/bff/events.test.ts', 'app/api/bff/events/route.test.ts']
T_FC = ['lib/fhir/client.stream.test.ts']
T_TL = ['components/board/Tile.test.tsx', 'components/board/Board.test.tsx']
T_BN = ['components/board/LastKnownBanner.test.tsx', 'components/board/Board.test.tsx']
T_LB = ['components/board/LiveBoard.test.tsx']
T_CL = ['lib/board/client.test.ts']

M = [
 # id, file, old, new, tests
 ('P1 parse: allow a negative count', PARSE, ' && p.valueInteger >= 0', '', T_PARSE),
 ('P2 parse: allow a fractional count', PARSE, 'Number.isSafeInteger(p.valueInteger) && ', '', T_PARSE),
 ('P3 parse: Number.isInteger instead of isSafeInteger', PARSE, 'Number.isSafeInteger(p.valueInteger)', 'Number.isInteger(p.valueInteger)', T_PARSE),
 ('P4 parse: zero refused (> 0)', PARSE, 'p.valueInteger >= 0', 'p.valueInteger > 0', T_PARSE),
 ('B1 json: allow a negative count', BJ, ' && value >= 0', '', T_BJ),
 ('B2 json: allow a fractional count', BJ, 'Number.isSafeInteger(value) && ', '', T_BJ),
 ('B3 json: accept an unknown status', BJ, "if (!isStatus(status)) fail('status is not one the board knows');", '', T_BJ),
 ('B4 json: accept any time text', BJ, "typeof value === 'string' && !Number.isNaN(Date.parse(value))", "typeof value === 'string'", T_BJ),
 ('B5 json: a missing optional count is null', BJ, "return source[key] === null ? null : count(source, key);", "return source[key] === null || source[key] === undefined ? null : count(source, key);", T_BJ),
 ('B6 json: carry unknown fields (spread)', BJ, "    serviceId: text(source, 'serviceId'),", "    ...source,\n    serviceId: text(source, 'serviceId'),", T_BJ),
 ('L1 live: old is >= limit', LV, 'ageMs > STALE_AFTER_MS', 'ageMs >= STALE_AFTER_MS', T_LV),
 ('L2 live: gap is >= 10 s', LV, 'nowLocal - health.streamDownSince > STREAM_GAP_MS', 'nowLocal - health.streamDownSince >= STREAM_GAP_MS', T_LV),
 ('L3 live: offline without the stream gap', LV, 'health.failingSince !== null && streamPaused', 'health.failingSince !== null', T_LV),
 ('L4 live: since is the latest failure (max)', LV, 'Math.min(...failures)', 'Math.max(...failures)', T_LV),
 ('L5 live: ignore the clock offset', LV, 'const serverNow = nowLocal + clockOffsetMs;', 'const serverNow = nowLocal;', T_LV),
 ('L6 live: allow a board from the future', LV, ' || ageMs < -MAX_FUTURE_SKEW_MS', '', T_LV),
 ('L7 live: future boundary <=', LV, 'ageMs < -MAX_FUTURE_SKEW_MS', 'ageMs <= -MAX_FUTURE_SKEW_MS', T_LV),
 ('L8 live: NaN time allowed', LV, ' || !Number.isFinite(ageMs)', '', T_LV),
 ('L9 live: unreadable not first (old wins)', LV, "  if (health.unreadableSince !== null || !Number.isFinite(ageMs) || ageMs < -MAX_FUTURE_SKEW_MS) {\n    reason = 'unreadable';\n  } else if (health.failingSince !== null && streamPaused) {\n    reason = 'offline';\n  } else if (ageMs > STALE_AFTER_MS) {\n    reason = 'old';\n  }", "  if (ageMs > STALE_AFTER_MS) {\n    reason = 'old';\n  } else if (health.unreadableSince !== null || !Number.isFinite(ageMs) || ageMs < -MAX_FUTURE_SKEW_MS) {\n    reason = 'unreadable';\n  } else if (health.failingSince !== null && streamPaused) {\n    reason = 'offline';\n  }", T_LV),
 ('L10 live: since for old is now, not build time', LV, "else if (Number.isFinite(builtAt) && reason === 'old') since = builtAt;", "", T_LV),
 ('H1 hook: an older board may replace', HK, 'if (builtAt >= Date.parse(board.generatedAt)) board = result.board;', 'board = result.board;', T_HK),
 ('H2 hook: same-time board refused (>)', HK, 'if (builtAt >= Date.parse(board.generatedAt))', 'if (builtAt > Date.parse(board.generatedAt))', T_HK),
 ('H3 hook: future board accepted', HK, ' || builtAt - (now() + offset) > MAX_FUTURE_SKEW_MS', '', T_HK),
 ('H4 hook: no poll', HK, 'const poll = setInterval(refetch, POLL_INTERVAL_MS);', 'const poll = setInterval(() => undefined, POLL_INTERVAL_MS);', T_HK),
 ('H5 hook: no refetch on open', HK, "        // Everything that changed while it was away: refetch the whole board.\n        refetch();", "", T_HK),
 ('H6 hook: no coalescing (always a new request)', HK, "      if (inFlight !== null) {\n        queued = true;\n        return;\n      }", "", T_HK),
 ('H7 hook: no retry after the browser gives up', HK, "          if (retryTimer === null && !stopped) {", "          if (false) {", T_HK),
 ('H8 hook: stream not closed on unmount', HK, "      source?.close();\n    };", "    };", T_HK),
 ('H9 hook: poll not cleared on unmount', HK, "      clearInterval(poll);\n", "", T_HK),
 ('H10 hook: in-flight not aborted on unmount', HK, "      inFlight?.abort();\n", "", T_HK),
 ('H11 hook: offline time is the latest failure', HK, "else health.failingSince ??= now();", "else health.failingSince = now();", T_HK),
 ('H12 hook: unreadable counted as a plain failure', HK, "if (known?.kind === 'unreadable') health.unreadableSince ??= now();", "if (false) health.unreadableSince ??= now();", T_HK),
 ('H13 hook: success does not clear failures', HK, "        health.failingSince = null;\n        health.unreadableSince = null;\n", "", T_HK),
 ('H14 hook: no timeout on a hung request', HK, "      fetchTimer = setTimeout(() => {", "      fetchTimer = setTimeout(() => {\n        if (true) return;", T_HK),
 ('H15 hook: no board event listener', HK, "export const REFRESH_EVENTS = ['board', 'board.updated'] as const;", "export const REFRESH_EVENTS = ['board.updated'] as const;", T_HK),
 ('H16 hook: booking events refresh the wall', HK, "export const REFRESH_EVENTS = ['board', 'board.updated'] as const;", "export const REFRESH_EVENTS = ['board', 'board.updated', 'booking.updated'] as const;", T_HK),
 ('H17 hook: no clock tick', HK, "const tick = setInterval(evaluate, TICK_MS);", "const tick = setInterval(() => undefined, TICK_MS);", T_HK),
 ('H18 hook: server clock offset not kept', HK, "if (result.serverTime !== null) offset = result.serverTime - now();", "", T_HK),
 ('H19 hook: screen refresh only on the first minute (ages frozen)', HK, "Math.floor(Date.parse(a.now) / MINUTE_MS) === Math.floor(Date.parse(b.now) / MINUTE_MS)", "true", T_HK),
 ('H20 hook: onUnpaired called every time', HK, "&& !unpairedSignalled) {", ") {", T_HK),
 ('H21 hook: onUnpaired for any status', HK, "known?.kind === 'refused' && known.status !== null && REFUSED_STATUSES.includes(known.status) &&", "known !== null &&", T_HK),
 ('H22 hook: stream down not counted from the start', HK, "      health.streamDownSince ??= now();\n      let opened", "      let opened", T_HK),
 ('H23 hook: first render ignores the server clock', HK, "nowLocal: options.serverTime,\n      clockOffsetMs: 0,", "nowLocal: Date.parse(options.initialBoard.generatedAt),\n      clockOffsetMs: 0,", T_HK),
 ('H24 hook: stream retry timer not cleared', HK, "      if (retryTimer !== null) clearTimeout(retryTimer);\n", "", T_HK),
 ('R1 relay: forward any event name', EV, "if (!RELAYED_EVENTS.includes(name)) return '';", "", T_EV),
 ('R2 relay: forward data unsanitised', EV, "event: ${name}\\ndata: ${sanitise(frame.data.join('\\n'))}", "event: ${name}\\ndata: ${frame.data.join('\\n')}", T_EV),
 ('R3 relay: no service id check', EV, "SERVICE_ID.test(serviceId)", "true", T_EV),
 ('R4 relay: no kind check', EV, "KINDS.includes(kind)", "true", T_EV),
 ('R5 relay: forward comment text', EV, "if (frame.event === null && frame.data.length === 0) return frame.comment ? KEEP_ALIVE : '';", "if (frame.event === null && frame.data.length === 0) return frame.comment ? ': ' + frame.data.join('') + KEEP_ALIVE : '';", T_EV),
 ('R6 relay: no frame size limit', EV, "if (this.frameChars > MAX_FRAME_CHARS) {", "if (false) {", T_EV),
 ('R7 relay: no time check', EV, "UTC_TIME.test(changedAt) && !Number.isNaN(Date.parse(changedAt))", "true", T_EV),
 ('R8 relay: no wait on a trailing CR', EV, "if (end[0] === '\\r' && end.index + 1 === this.buffer.length) break;", "", T_EV),
 ('R9 relay: onCancel not called', EV, "      options.onCancel?.();\n", "", T_EV),
 ('R10 relay: signal abort does not stop it', EV, "options.signal?.addEventListener('abort', stop, { once: true });", "", T_EV),
 ('R11 relay: unnamed event allowed as message', EV, "frame.event === null || frame.event === '' ? 'message' : frame.event;", "frame.event === null || frame.event === '' ? 'board' : frame.event;", T_EV),
 ('T1 route: no role check', RT, "  { roles: [...BOARD_ROLES] },", "  {},", T_EV),
 ('T2 route: compression allowed (no no-transform)', RT, "'no-store, no-transform'", "'no-store'", T_EV),
 ('T3 route: upstream not closed on abort', RT, "request.signal.addEventListener('abort', () => closeUpstream.abort(), { once: true });", "", T_EV),
 ('T4 route: browser cancel does not close upstream', RT, "onCancel: () => closeUpstream.abort()", "onCancel: () => undefined", T_EV),
 ('T5 route: upstream gets the query string', RT, "fhirStream('/events',", "fhirStream('/events' + new URL(request.url).search,", T_EV),
 ('S1 stream: any content type accepted', FC, "if (!isStream || response.body === null) {", "if (response.body === null) {", T_FC),
 ('S2 stream: no bearer token', FC, "  if (init.token) headers.set('Authorization', `Bearer ${init.token}`);\n\n  let response: Response;\n  try {\n    response = await fetch(url, { method: 'GET', headers, signal", "  let response: Response;\n  try {\n    response = await fetch(url, { method: 'GET', headers, signal", T_FC),
 ('S3 stream: signal not passed', FC, "{ method: 'GET', headers, signal: init.signal, cache: 'no-store' }", "{ method: 'GET', headers, cache: 'no-store' }", T_FC),
 ('C1 tile: last known keeps the current look', TL, "const variant = lastKnown ? styles.notUpdated : VARIANT[entry.status];", "const variant = VARIANT[entry.status];", T_TL),
 ('C2 tile: last known shows the comment', TL, "          {lastKnown ? (\n            <p className={styles.meta}", "          {lastKnown && entry.comment === 'never' ? (\n            <p className={styles.meta}", T_TL),
 ('C3 tile: last known repeats out-of-hours', TL, "entry.status === 'not-updated' || entry.status === 'out-of-hours'\n    ? unknownFigure", "entry.status === 'not-updated'\n    ? unknownFigure", T_TL),
 ('C4 tile: last known keeps a number for not updated', TL, "entry.status === 'not-updated' || entry.status === 'out-of-hours'\n    ? unknownFigure", "entry.status === 'never'\n    ? unknownFigure", T_TL),
 ('C5 tile: no warning line', TL, "<strong>{LAST_KNOWN_WARNING}</strong>", "<span>{LAST_KNOWN_WARNING}</span>", T_TL),
 ('C6 tile: status word kept as current', TL, "<StatusBadge status={lastKnown ? 'last-known' : entry.status} size=\"lg\" />", "<StatusBadge status={entry.status} size=\"lg\" />", T_TL),
 ('C7 tile: no age beside the time', TL, "<span>{` · ${dataAgeText(entry.reportedAt, now)}`}</span>", "", T_TL),
 ('C8 tile: data-status stays current', TL, "data-status={lastKnown ? 'last-known' : entry.status}", "data-status={entry.status}", T_TL),
 ('D1 board: no banner', BD, "      {lastKnown ? (\n        <LastKnownBanner lastKnown={lastKnown} />", "      {lastKnown && false ? (\n        <LastKnownBanner lastKnown={lastKnown} />", T_TL),
 ('D2 board: header time follows now', BD, "dateTime={board.generatedAt}>\n            {londonTime(board.generatedAt)}", "dateTime={board.generatedAt}>\n            {londonTime(now)}", T_TL),
 ('D3 board: ages stay from the build time', BD, "const now = lastKnown ? lastKnown.now : board.generatedAt;", "const now = board.generatedAt;", T_TL),
 ('D4 board: tiles not last known', BD, "lastKnown={lastKnown !== undefined}", "lastKnown={false}", T_TL),
 ('D5 board: stream note always on', BD, ") : streamPaused ? (", ") : true ? (", T_TL),
 ('N1 banner: not an alert', BN, '<div role="alert" className={styles.banner}', '<div className={styles.banner}', T_BN),
 ('N2 banner: ages inside the alert', BN, "        <p className={styles.body}>\n          Figures are the last known and may be wrong. Use the whiteboard and phone process.\n        </p>\n      </div>\n      <p className={styles.refreshed} data-el=\"WALL-LAST-REFRESH\">\n        {`Board last refreshed ${londonTime(lastKnown.asOf)} · ${dataAgeText(lastKnown.asOf, lastKnown.now)}`}\n      </p>", "        <p className={styles.body}>\n          Figures are the last known and may be wrong. Use the whiteboard and phone process.\n        </p>\n      <p className={styles.refreshed} data-el=\"WALL-LAST-REFRESH\">\n        {`Board last refreshed ${londonTime(lastKnown.asOf)} · ${dataAgeText(lastKnown.asOf, lastKnown.now)}`}\n      </p>\n      </div>", T_BN),
 ('N3 banner: offline time is the board time', BN, "londonTime(lastKnown.since)}`}</p>", "londonTime(lastKnown.asOf)}`}</p>", T_BN),
 ('V1 live board: unpaired does nothing', LB, "onUnpaired: onUnpaired ?? (() => router.replace(PAIR)),", "onUnpaired: onUnpaired ?? (() => undefined),", T_LB),
 ('V2 live board: stream url carries a query', LB, "new EventSource(STREAM_URL)", "new EventSource(STREAM_URL + '?scope=network')", T_LB),
 ('V3 live board: stream paused flag dropped', LB, "<Board board={board} streamPaused={assessment.streamPaused} />", "<Board board={board} />", T_LB),
 ('F1 client: 502 is just unreachable', CL, "if (status === 502) return 'unreadable';", "", T_CL),
 ('F2 client: 404 not refused', CL, "[401, 403, 404]", "[401, 403]", T_CL),
 ('F3 client: board cached', CL, "cache: 'no-store', ", "", T_CL),
 ('F4 client: body not validated', CL, "return { board: parseBoardJson(body), serverTime", "return { board: body as Board, serverTime", T_CL),
 ('F5 client: server clock ignored', CL, "const time = Date.parse(response.headers.get('Date') ?? '');", "const time = Number.NaN;", T_CL),
]

only = sys.argv[1:]
lines = []
survivors = []
for (name, rel, old, new, tests) in M:
    if only and not any(name.startswith(o + ' ') for o in only):
        continue
    path = ROOT / rel
    original = path.read_bytes()
    text = original.decode()
    if old not in text:
        lines.append(f'NOT APPLIED  {name}  (old text not found)')
        survivors.append(name + ' [not applied]')
        continue
    if text.count(old) != 1:
        lines.append(f'AMBIGUOUS    {name}  ({text.count(old)} matches)')
        survivors.append(name + ' [ambiguous]')
        continue
    try:
        path.write_text(text.replace(old, new))
        r = subprocess.run(['pnpm', 'vitest', 'run', *tests], cwd=ROOT, capture_output=True, text=True, timeout=300)
        out = r.stdout + r.stderr
        summary = [l for l in out.splitlines() if 'Tests ' in l]
        status = 'KILLED  ' if r.returncode != 0 else 'SURVIVED'
        if r.returncode == 0:
            survivors.append(name)
        lines.append(f'{status}  {name}  {summary[-1].strip() if summary else ""}')
    finally:
        path.write_bytes(original)
    print(lines[-1], flush=True)
OUT.write_text('\n'.join(lines) + '\n\nSurvivors: ' + (', '.join(survivors) if survivors else 'none') + '\n')
print('done; survivors:', survivors)
