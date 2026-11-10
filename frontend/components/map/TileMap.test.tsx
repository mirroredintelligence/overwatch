import { act, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// The zoomable map shows the placeholder until the style has loaded, then it falls away (DEC-1371).

type Handler = () => void;
const handlers = new Map<string, Handler>();

vi.mock('maplibre-gl/dist/maplibre-gl.css', () => ({}));
vi.mock('pmtiles', () => ({
  Protocol: class {
    tile = () => undefined;
    tiles = new Map();
    add() {}
  },
  PMTiles: class {
    getHeader() {
      return Promise.resolve({});
    }
  },
}));
vi.mock('maplibre-gl', () => {
  class LngLatBounds {
    extend() {
      return this;
    }
  }
  class FakeMap {
    touchZoomRotate = { disableRotation: () => undefined };
    on(name: string, handler: Handler) {
      handlers.set(name, handler);
    }
    addControl() {}
    addSource() {}
    addLayer() {}
    addImage() {}
    getSource() {
      return { setData: () => undefined };
    }
    remove() {}
  }
  class NavigationControl {}
  class Marker {
    setLngLat() {
      return this;
    }
    addTo() {
      return this;
    }
    remove() {}
  }
  return { LngLatBounds, Map: FakeMap, NavigationControl, Marker, addProtocol: () => undefined, setWorkerUrl: () => undefined };
});

import { TileMap } from './TileMap';

const props = {
  fit: [{ lat: 50.7, lon: -2.4 }],
  areas: [],
  route: null,
  markers: [],
  onFailed: vi.fn(),
};

describe('TileMap loading', () => {
  beforeEach(() => {
    handlers.clear();
    props.onFailed.mockClear();
  });

  it('shows the placeholder at once, and drops it when the map has loaded', async () => {
    render(<TileMap {...props} />);
    expect(screen.getByText('Loading the map.')).toBeTruthy();
    await vi.waitFor(() => expect(handlers.has('load')).toBe(true));
    expect(screen.getByText('Loading the map.')).toBeTruthy();
    act(() => handlers.get('load')?.());
    expect(screen.queryByText('Loading the map.')).toBeNull();
  });

  it('leaves the failure to the caller: a map that cannot load calls onFailed', async () => {
    render(<TileMap {...props} />);
    await vi.waitFor(() => expect(handlers.has('error')).toBe(true));
    act(() => handlers.get('error')?.());
    expect(props.onFailed).toHaveBeenCalledTimes(1);
  });
});
