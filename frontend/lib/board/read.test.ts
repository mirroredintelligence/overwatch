import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FhirError } from '@/lib/fhir/client';
import { BOARD_A, BOARD_B } from '@/test/fixtures/board';
import {
  BACKEND_BASE,
  BOARD_URL,
  resetSeenBoardRequests,
  seenBoardRequests,
  TOKEN_ORG_A,
  TOKEN_ORG_B,
} from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { BOARD_ROLES, canReadBoard, readBoard } from './read';

beforeEach(() => {
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  resetSeenBoardRequests();
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('BOARD_ROLES and canReadBoard', () => {
  it('are the four roles the prompt names', () => {
    expect([...BOARD_ROLES].sort()).toEqual(['advisor', 'exec', 'lead', 'wall']);
  });

  it.each(['wall', 'advisor', 'lead', 'exec'] as const)('allows %s', (role) => {
    expect(canReadBoard(role)).toBe(true);
  });

  it.each(['reporter', 'clinical', 'owner', 'anonymous-link', 'support', 'audit'] as const)('refuses %s', (role) => {
    expect(canReadBoard(role)).toBe(false);
  });
});

describe('readBoard', () => {
  it('returns the board the token is for, parsed', async () => {
    expect(await readBoard({ backendToken: TOKEN_ORG_A })).toEqual(BOARD_A);
    expect(await readBoard({ backendToken: TOKEN_ORG_B })).toEqual(BOARD_B);
  });

  it('sends one GET to $board with the bearer token and nothing that names an organisation', async () => {
    await readBoard({ backendToken: TOKEN_ORG_A });

    expect(seenBoardRequests).toHaveLength(1);
    expect(seenBoardRequests[0].headers.get('authorization')).toBe(`Bearer ${TOKEN_ORG_A}`);
    expect(new URL(seenBoardRequests[0].url).search).toBe('');
  });

  it('throws a 502 FhirError, with no body text, for a board it cannot read', async () => {
    server.use(http.get(BOARD_URL, () => HttpResponse.json({ resourceType: 'Parameters', parameter: [{ name: 'entry' }] })));

    const failure = await readBoard({ backendToken: TOKEN_ORG_A }).then(
      () => null,
      (error: unknown) => error,
    );

    expect(failure).toBeInstanceOf(FhirError);
    expect((failure as FhirError).status).toBe(502);
    expect(JSON.stringify((failure as FhirError).outcome)).not.toContain('entry');
  });

  it('lets a back-end refusal through unchanged', async () => {
    const failure = await readBoard({ backendToken: 'not-a-token' }).then(
      () => null,
      (error: unknown) => error,
    );

    expect((failure as FhirError).status).toBe(401);
  });
});
