import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DistrictCheckPanel } from './DistrictCheck';

// The two steps of a postcode district (DEC-1329): the check shows the count, and a confirm queues the
// district; the page does not wait for the download.

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
  document.cookie = 'overwatch_csrf=token-1';
});

afterEach(() => {
  vi.unstubAllGlobals();
  document.cookie = 'overwatch_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT';
});

function answer(status: number, body?: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('the postcode district check', () => {
  it('checks each district typed and shows its postcode count', async () => {
    fetchMock.mockResolvedValueOnce(answer(200, { prefix: 'DT4', postcodes: 1505 }));
    render(<DistrictCheckPanel text="dt4" />);
    fireEvent.click(screen.getByRole('button', { name: 'Check districts' }));
    expect(await screen.findByText(/DT4: 1,505 postcodes/)).toBeInTheDocument();
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/bff/postcode-districts/check?text=DT4');
  });

  it('says a district with no postcodes is not found, and never shows a count for it', async () => {
    fetchMock.mockResolvedValueOnce(answer(422, { errors: [] }));
    render(<DistrictCheckPanel text="ZZ99" />);
    fireEvent.click(screen.getByRole('button', { name: 'Check districts' }));
    expect(await screen.findByText('ZZ99: not a district with postcodes')).toBeInTheDocument();
    expect(screen.queryByText(/\d postcodes/)).toBeNull();
  });

  it('says a check that cannot answer could not be checked, rather than not found', async () => {
    fetchMock.mockResolvedValueOnce(answer(503, {}));
    render(<DistrictCheckPanel text="DT4" />);
    fireEvent.click(screen.getByRole('button', { name: 'Check districts' }));
    expect(await screen.findByText('DT4: could not be checked, try again')).toBeInTheDocument();
  });

  it('a confirmed district is queued, and the page says the download runs in the background', async () => {
    fetchMock
      .mockResolvedValueOnce(answer(200, { prefix: 'DT4', postcodes: 3 }))
      .mockResolvedValueOnce(answer(202, { prefix: 'DT4', status: 'queued' }));
    render(<DistrictCheckPanel text="DT4" />);
    fireEvent.click(screen.getByRole('button', { name: 'Check districts' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Confirm DT4' }));
    expect(await screen.findByText(/queued\. The postcodes download in the background/)).toBeInTheDocument();
    const [url, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(url).toBe('/api/bff/postcode-districts/download?text=DT4');
    expect(init.method).toBe('POST');
  });

  it('a confirm that fails says it could not be queued, and the district is not shown as queued', async () => {
    fetchMock
      .mockResolvedValueOnce(answer(200, { prefix: 'DT4', postcodes: 3 }))
      .mockResolvedValueOnce(answer(503, {}));
    render(<DistrictCheckPanel text="DT4" />);
    fireEvent.click(screen.getByRole('button', { name: 'Check districts' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Confirm DT4' }));
    expect(await screen.findByText('DT4: could not be queued, try again')).toBeInTheDocument();
    expect(screen.queryByText(/queued\./)).toBeNull();
  });
});
