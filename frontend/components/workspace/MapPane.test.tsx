import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import type { FoundService } from '@/lib/advisor/v2/find';
import { MapPane } from './MapPane';

// maplibre cannot run in jsdom: the tile map is replaced by a stand-in that renders the pins it is given and
// reports the areas it is told to draw. With `tiles.on` false the pane draws its schematic, which is what jsdom
// gets by itself (no WebGL).
const tiles = vi.hoisted(() => ({ on: false }));
vi.mock('@/components/map/TileMap', () => ({
  useWebgl: () => tiles.on,
  useMapPreload: () => undefined,
  TileMap: ({ areas, markers }: { areas: unknown[]; markers: { id: string; node: ReactNode }[] }) => (
    <div data-testid="tile-map" data-areas={areas.length}>
      {markers.map((marker) => (
        <div key={marker.id}>{marker.node}</div>
      ))}
    </div>
  ),
}));

function service(id: string, over: Partial<FoundService> = {}): FoundService {
  return {
    serviceId: id,
    name: `Service ${id}`,
    category: 'other',
    status: 'accepting',
    effectiveAvailable: 2,
    overBy: null,
    unitLabel: null,
    dataAgeSeconds: 60,
    reportedAt: null,
    nextDueAt: null,
    cadence: null,
    overdue: false,
    staleWarning: false,
    figureUnavailable: false,
    lastFigure: null,
    criteriaVersion: 1,
    fits: [],
    warnings: [],
    phone: null,
    travel: null,
    position: { lat: 50.6, lon: -2.4 },
    coverage: { districts: [], circle: null },
    ...over,
  };
}

const SITE = service('a', { name: 'Site A', position: { lat: 50.61, lon: -2.45 } });
const LIMITED = service('b', { name: 'Site B', status: 'limited', position: { lat: 50.62, lon: -2.4 } });
const VISITS = service('c', {
  name: 'Visiting C',
  position: null,
  coverage: { districts: ['XX1'], circle: { lat: 50.65, lon: -2.3, radiusMeters: 8000 } },
});
const NOWHERE = service('d', { name: 'Nowhere D', position: null });
const PATIENT = { lat: 50.7, lon: -2.2 };

function pane(over: Partial<React.ComponentProps<typeof MapPane>> = {}) {
  const onOpen = vi.fn();
  const result = render(<MapPane services={[SITE, LIMITED, VISITS, NOWHERE]} patient={null} onOpen={onOpen} {...over} />);
  return { onOpen, ...result };
}

const circles = (container: HTMLElement) => container.querySelectorAll('[data-el="ADV-MAP-COVER-AREA"]');

beforeEach(() => {
  tiles.on = false;
});

describe.each([
  ['schematic', false],
  ['tile map', true],
])('MapPane (%s)', (_name, on) => {
  beforeEach(() => {
    tiles.on = on;
  });

  it('draws one pin per service with a position, named by the service and its status word', () => {
    pane();
    expect(screen.getByRole('button', { name: 'Site A, Accepting' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Site B, Limited' })).toBeInTheDocument();
  });

  it('gives a service without a position no pin', () => {
    pane({ services: [SITE, NOWHERE] });
    expect(screen.queryByRole('button', { name: /Nowhere D/ })).toBeNull();
    expect(screen.getAllByRole('button', { name: /, (Accepting|Limited)/ })).toHaveLength(1);
  });

  it('draws the patient pin only when a patient place is given', () => {
    const { unmount } = pane();
    expect(screen.queryByText('Patient')).toBeNull();
    unmount();
    pane({ patient: PATIENT });
    expect(screen.getByText('Patient')).toBeInTheDocument();
  });

  it('has a coverage layer toggle, on by default, that adds and removes the circles', async () => {
    const { container } = pane();
    const toggle = screen.getByRole('button', { name: 'Who covers this area' });
    expect(toggle).toHaveAttribute('aria-pressed', 'true');
    const count = () => (on ? Number(screen.getByTestId('tile-map').dataset.areas) : circles(container).length);
    expect(count()).toBe(1);
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-pressed', 'false');
    expect(count()).toBe(0);
    await userEvent.click(toggle);
    expect(count()).toBe(1);
  });

  it('draws no circle for a service that has none', () => {
    const { container } = pane({ services: [SITE, LIMITED] });
    const areas = on ? Number(screen.getByTestId('tile-map').dataset.areas) : circles(container).length;
    expect(areas).toBe(0);
  });

  it('calls onOpen with the service when its pin is chosen, by mouse or keyboard', async () => {
    const { onOpen } = pane();
    await userEvent.click(screen.getByRole('button', { name: 'Site A, Accepting' }));
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onOpen).toHaveBeenCalledWith(SITE);
    screen.getByRole('button', { name: 'Site B, Limited' }).focus();
    await userEvent.keyboard('{Enter}');
    expect(onOpen).toHaveBeenLastCalledWith(LIMITED);
  });

  it('draws a visiting service as a pin at its circle centre when it has no site', () => {
    pane();
    expect(screen.getByRole('button', { name: 'Visiting C (visits), Accepting' })).toBeInTheDocument();
  });

  it('does not repeat the list caption (the results canvas says how the list is sorted, once)', () => {
    pane();
    expect(screen.queryByText(/Same services as the list/)).toBeNull();
  });

  it('has no axe violations', async () => {
    const { container } = pane({ patient: PATIENT });
    expect((await runAxe(container)).violations).toEqual([]);
  });
});

describe('MapPane with nothing to place', () => {
  it('says so, with no map and no toggle', () => {
    pane({ services: [NOWHERE], patient: null });
    expect(screen.getByText('No locations are held for these services.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Who covers this area' })).toBeNull();
  });

  it('draws the map when only the patient has a place', () => {
    pane({ services: [NOWHERE], patient: PATIENT });
    expect(screen.queryByText('No locations are held for these services.')).toBeNull();
    expect(screen.getByText('Patient')).toBeInTheDocument();
  });

  it('keeps the basemap attribution visible in the schematic', () => {
    pane();
    expect(screen.getByText(/Office for National Statistics/)).toBeInTheDocument();
  });
});
