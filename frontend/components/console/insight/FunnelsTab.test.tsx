import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { FunnelsTab } from './FunnelsTab';

const FUNNEL = {
  name: 'reporter-setup',
  label: 'Reporter set-up',
  steps: [
    { name: 'Link sent', pct: 100, count: 412, suppressed: false },
    { name: 'Link opened', pct: 95, count: 391, suppressed: false, exitElementId: 'L-CODE-INPUT', medianSeconds: 42 },
    { name: 'Code verified', pct: 84, count: 346, suppressed: false },
    { name: 'Tiny step', pct: null, count: null, suppressed: true },
  ],
  split: [
    { channel: 'Text link', pct: 80, suppressed: false },
    { channel: 'Email link', pct: null, suppressed: true },
    { channel: 'App', pct: 60, suppressed: false },
  ],
};

// jsdom's Blob has no text(), and a Response would stringify it, so the file is read with a FileReader.
function readBlob(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(blob);
  });
}

describe('FunnelsTab', () => {
  it('shows fewer than 10 and no bar for a suppressed step', () => {
    const { container } = render(<FunnelsTab funnel={FUNNEL} />);

    const tiny = within(screen.getByRole('list', { name: /funnel steps/i })).getByText('Tiny step').closest('li');
    expect(tiny).toHaveTextContent('fewer than 10');
    expect(tiny?.querySelector('[data-bar]')).toBeNull();
    expect(container.querySelectorAll('[data-bar]')).toHaveLength(3);
  });

  it('gives every shown bar its value as text', () => {
    render(<FunnelsTab funnel={FUNNEL} />);

    expect(screen.getByText('95%')).toBeInTheDocument();
    expect(screen.getByText('84%')).toBeInTheDocument();
  });

  it('shows the change in points from the step before, with a minus sign, and none for the first step', () => {
    render(<FunnelsTab funnel={FUNNEL} />);

    const steps = screen.getByRole('list', { name: /funnel steps/i });
    expect(within(steps).getByText('Link sent').closest('li')).not.toHaveTextContent('−');
    expect(within(steps).getByText('Link opened').closest('li')).toHaveTextContent('−5');
    expect(within(steps).getByText('Code verified').closest('li')).toHaveTextContent('−11');
  });

  it('draws the step with the biggest drop hatched and names it biggest in words', () => {
    render(<FunnelsTab funnel={FUNNEL} />);

    const steps = screen.getByRole('list', { name: /funnel steps/i });
    const biggest = within(steps).getByText('Code verified').closest('li');
    expect(biggest).toHaveTextContent('biggest');
    expect(biggest?.querySelector('[data-drop]')).not.toBeNull();
    const other = within(steps).getByText('Link opened').closest('li');
    expect(other?.querySelector('[data-drop]')).toBeNull();
    expect(other).not.toHaveTextContent('biggest');
  });

  it('names the biggest drop with its points, exit element and median time between steps, in a card of its own', () => {
    render(<FunnelsTab funnel={FUNNEL} />);

    const card = screen.getByRole('region', { name: 'Biggest drop' });
    expect(card).toHaveTextContent('Link opened to Code verified: 11 points');
    expect(card).toHaveTextContent('Exit element: L-CODE-INPUT');
    expect(card).toHaveTextContent('Median time between steps: 42 s');
  });

  it('shows the split by channel, with a suppressed channel as fewer than 10', () => {
    render(<FunnelsTab funnel={FUNNEL} />);

    const split = screen.getByRole('table', { name: /by channel/i });
    expect(within(split).getByRole('row', { name: /Email link/ })).toHaveTextContent('fewer than 10');
    expect(within(split).getByRole('columnheader', { name: 'Conversion' })).toBeInTheDocument();
  });

  it('exports the steps and the split as a CSV file named for the funnel', async () => {
    const createObjectURL = vi.fn<(blob: Blob) => string>(() => 'blob:funnel');
    const revokeObjectURL = vi.fn();
    const downloaded: string[] = [];
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL, revokeObjectURL }));
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      downloaded.push(this.download);
    });

    render(<FunnelsTab funnel={FUNNEL} />);
    await userEvent.click(screen.getByRole('button', { name: 'Export CSV' }));

    expect(downloaded).toEqual(['reporter-setup.csv']);
    const blob = createObjectURL.mock.calls[0]?.[0];
    expect(blob).toBeDefined();
    const text = await readBlob(blob as Blob);
    expect(text).toContain('"Link opened","95","391"');
    expect(text).toContain('"Email link","fewer than 10"');
    expect(text).toContain('"Tiny step","fewer than 10","fewer than 10"');
  });

  it('passes vitest-axe', async () => {
    const { container } = render(<FunnelsTab funnel={FUNNEL} />);

    expect(await runAxe(container)).toHaveNoViolations();
  });
});

describe('FunnelsTab: the CSV export is cleaned up after the click', () => {
  beforeEach(() => {
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('revokes the object URL it made', async () => {
    const createObjectURL = vi.fn<(blob: Blob) => string>(() => 'blob:funnel');
    const revokeObjectURL = vi.fn();
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL, revokeObjectURL }));

    render(<FunnelsTab funnel={FUNNEL} />);
    await userEvent.click(screen.getByRole('button', { name: 'Export CSV' }));

    await vi.waitFor(() => expect(revokeObjectURL).toHaveBeenCalledWith('blob:funnel'));
  });
});
