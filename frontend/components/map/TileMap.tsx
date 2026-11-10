'use client';

import 'maplibre-gl/dist/maplibre-gl.css';
import type { Map as MapLibreMap, Marker } from 'maplibre-gl';
import { useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { circleRing } from '@/lib/map/geo';
import type { LatLon } from '@/lib/map/project';
import { ATTRIBUTION, mapStyle, TILES_PATH } from '@/lib/map/style';
import { MapPlaceholder } from './MapPlaceholder';
import styles from './tileMap.module.css';

// The zoomable map (DEC-1362): OS Open Zoomstack tiles read through this app's own tile route, with the service
// areas and the route as map layers and each pin as an HTML button the map moves. It is drawn only where the
// browser can run WebGL and the tiles answer; otherwise `onFailed` is called and the caller keeps its schematic.

export type TileArea = { id: string; centre: LatLon; radiusKm: number; color: string; dash: boolean; fillOpacity: number };
export type TileMarker = { id: string; at: LatLon; anchor: 'bottom' | 'center'; node: ReactNode };

export type TileMapProps = {
  /** Every place the first view must hold: the patient, the pins and the edges of the areas. */
  fit: LatLon[];
  areas: TileArea[];
  route: [LatLon, LatLon] | null;
  /** The ground two areas share, each a ring, drawn hatched. */
  overlaps?: LatLon[][];
  markers: TileMarker[];
  onFailed: () => void;
};

let webgl: boolean | null = null;

/** Whether this browser can run WebGL (not in the server render, not in jsdom). Asked once. */
export function webglAvailable(): boolean {
  if (webgl !== null) return webgl;
  try {
    const canvas = document.createElement('canvas');
    webgl = Boolean(canvas.getContext('webgl2') ?? canvas.getContext('webgl'));
  } catch {
    webgl = false;
  }
  return webgl;
}

const noSubscription = () => () => undefined;

/** True once the page is in a browser that can draw the map; false in the server render, so the two renders match. */
export function useWebgl(): boolean {
  return useSyncExternalStore(noSubscription, webglAvailable, () => false);
}

// MapLibre cannot read a CSS variable, so a `var(--c-x)` colour is read from the page here.
function resolveColor(color: string): string {
  const match = /^var\((--[A-Za-z0-9-]+)\)$/.exec(color);
  if (match === null) return color;
  return getComputedStyle(document.documentElement).getPropertyValue(match[1]).trim() || '#0B5A8A';
}

/** MapLibre's worker, copied from the package into public/map (a test keeps its version the package's). */
export const WORKER_URL = '/map/maplibre-gl-worker.mjs';

// The map's code, the tile protocol and the first bytes of the tile file are asked for as early as the page can,
// so they arrive while the options are still being read and not after (DEC-1371). Everything here runs once.
let libraries: Promise<[typeof import('maplibre-gl'), typeof import('pmtiles')]> | null = null;

function loadLibraries() {
  libraries ??= Promise.all([import('maplibre-gl'), import('pmtiles')]).then(([maplibre, pmtiles]) => {
    const protocol = new pmtiles.Protocol();
    maplibre.addProtocol('pmtiles', protocol.tile);
    // The worker is a file we serve (public/map), not one the bundler guesses at, and it is on our own origin.
    maplibre.setWorkerUrl(WORKER_URL);
    // The header and the root directory (one 16 KB read) are what the first tile waits for; ask for them now. A
    // failed read is forgotten, so the map's own first read tries again and reports the failure.
    const url = `${window.location.origin}${TILES_PATH}`;
    const archive = new pmtiles.PMTiles(url);
    protocol.add(archive);
    archive.getHeader().catch(() => protocol.tiles.delete(url));
    return [maplibre, pmtiles] as [typeof import('maplibre-gl'), typeof import('pmtiles')];
  });
  // A failed load is not kept: the next ask tries again.
  libraries.catch(() => {
    libraries = null;
  });
  return libraries;
}

/** Starts loading the map's code, its worker and the start of the tile file. Safe to call again and from anywhere in the browser. */
export function preloadMap(): void {
  if (!webglAvailable()) return;
  void loadLibraries().catch(() => undefined);
  void fetch(WORKER_URL, { priority: 'low' } as RequestInit).catch(() => undefined);
}

/** A screen that will show a map calls this while it reads what the map draws. */
export function useMapPreload(): void {
  useEffect(() => {
    preloadMap();
  }, []);
}

function areasData(areas: TileArea[]) {
  return {
    type: 'FeatureCollection' as const,
    features: areas.map((area) => ({
      type: 'Feature' as const,
      id: area.id,
      properties: { color: resolveColor(area.color), dash: area.dash, fillOpacity: area.fillOpacity },
      geometry: { type: 'Polygon' as const, coordinates: [circleRing(area.centre, area.radiusKm)] },
    })),
  };
}

function routeData(route: [LatLon, LatLon] | null) {
  return {
    type: 'FeatureCollection' as const,
    features:
      route === null
        ? []
        : [
            {
              type: 'Feature' as const,
              properties: {},
              geometry: { type: 'LineString' as const, coordinates: route.map((point) => [point.lon, point.lat]) },
            },
          ],
  };
}

const NO_OVERLAPS: LatLon[][] = [];

function overlapsData(rings: LatLon[][]) {
  return {
    type: 'FeatureCollection' as const,
    features: rings.map((ring) => ({
      type: 'Feature' as const,
      properties: {},
      geometry: { type: 'Polygon' as const, coordinates: [[...ring, ring[0]].map((point) => [point.lon, point.lat])] },
    })),
  };
}

// A diagonal hatch, 8 by 8 pixels, made in memory (no image file is loaded).
function hatchImage() {
  const size = 8;
  const data = new Uint8ClampedArray(size * size * 4);
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      if ((x + y) % size < 3) data.set([20, 35, 43, 255], (y * size + x) * 4);
    }
  }
  return { width: size, height: size, data };
}

type Settable = { setData(data: unknown): void };

export function TileMap({ fit, areas, route, overlaps = NO_OVERLAPS, markers, onFailed }: TileMapProps) {
  const container = useRef<HTMLDivElement | null>(null);
  const map = useRef<MapLibreMap | null>(null);
  const live = useRef<Map<string, { marker: Marker; host: HTMLDivElement }>>(new Map());
  const [ready, setReady] = useState(false);
  const [hosts, setHosts] = useState<Map<string, HTMLDivElement>>(new Map());
  const latest = useRef({ areas, route, overlaps, fit, onFailed });
  useEffect(() => {
    latest.current = { areas, route, overlaps, fit, onFailed };
  });

  // The map itself, once.
  useEffect(() => {
    let cancelled = false;
    let created: MapLibreMap | null = null;
    const markersLive = live.current;
    void (async () => {
      try {
        const [maplibre] = await loadLibraries();
        if (cancelled || container.current === null) return;
        const points = latest.current.fit;
        const bounds = points.reduce(
          (box, point) => box.extend([point.lon, point.lat]),
          new maplibre.LngLatBounds([points[0].lon, points[0].lat], [points[0].lon, points[0].lat]),
        );
        const instance = new maplibre.Map({
          container: container.current,
          style: mapStyle(window.location.origin),
          bounds,
          fitBoundsOptions: { padding: 70, maxZoom: 13 },
          minZoom: 5,
          maxZoom: 16,
          cooperativeGestures: true,
          attributionControl: { compact: true },
          dragRotate: false,
          pitchWithRotate: false,
        });
        created = instance;
        instance.touchZoomRotate.disableRotation();
        instance.addControl(new maplibre.NavigationControl({ showCompass: false }), 'top-right');
        let loaded = false;
        instance.on('error', () => {
          if (!loaded && !cancelled) latest.current.onFailed();
        });
        instance.on('load', () => {
          if (cancelled) return;
          loaded = true;
          instance.addSource('areas', { type: 'geojson', data: areasData(latest.current.areas) });
          instance.addSource('route', { type: 'geojson', data: routeData(latest.current.route) });
          instance.addLayer({ id: 'area-fill', type: 'fill', source: 'areas', paint: { 'fill-color': ['get', 'color'], 'fill-opacity': ['get', 'fillOpacity'] } });
          instance.addLayer({ id: 'area-solid', type: 'line', source: 'areas', filter: ['!', ['get', 'dash']], paint: { 'line-color': ['get', 'color'], 'line-width': 3 } });
          instance.addLayer({ id: 'area-dash', type: 'line', source: 'areas', filter: ['get', 'dash'], paint: { 'line-color': ['get', 'color'], 'line-width': 3, 'line-dasharray': [3, 2] } });
          instance.addImage('hatch', hatchImage());
          instance.addSource('overlaps', { type: 'geojson', data: overlapsData(latest.current.overlaps) });
          instance.addLayer({ id: 'overlap-hatch', type: 'fill', source: 'overlaps', paint: { 'fill-pattern': 'hatch', 'fill-opacity': 0.3 } });
          instance.addLayer({ id: 'route-line', type: 'line', source: 'route', layout: { 'line-cap': 'round' }, paint: { 'line-color': '#14232B', 'line-width': 3, 'line-dasharray': [0.1, 2.2] } });
          map.current = instance;
          setReady(true);
        });
      } catch {
        if (!cancelled) latest.current.onFailed();
      }
    })();
    return () => {
      cancelled = true;
      markersLive.clear();
      map.current = null;
      created?.remove();
    };
  }, []);

  useEffect(() => {
    if (!ready) return;
    (map.current?.getSource('areas') as Settable | undefined)?.setData(areasData(areas));
  }, [areas, ready]);

  useEffect(() => {
    if (!ready) return;
    (map.current?.getSource('overlaps') as Settable | undefined)?.setData(overlapsData(overlaps));
  }, [overlaps, ready]);

  useEffect(() => {
    if (!ready) return;
    (map.current?.getSource('route') as Settable | undefined)?.setData(routeData(route));
  }, [route, ready]);

  // The pins: one wrapper element each, moved by the map, with the pin's own markup portalled into it.
  useEffect(() => {
    const current = map.current;
    if (!ready || current === null) return;
    let cancelled = false;
    void import('maplibre-gl').then((maplibre) => {
      if (cancelled) return;
      const wanted = new Set(markers.map((marker) => marker.id));
      for (const [id, entry] of live.current) {
        if (!wanted.has(id)) {
          entry.marker.remove();
          live.current.delete(id);
        }
      }
      for (const marker of markers) {
        const existing = live.current.get(marker.id);
        if (existing !== undefined) {
          existing.marker.setLngLat([marker.at.lon, marker.at.lat]);
          continue;
        }
        const host = document.createElement('div');
        host.className = styles.marker;
        const placed = new maplibre.Marker({ element: host, anchor: marker.anchor }).setLngLat([marker.at.lon, marker.at.lat]).addTo(current);
        live.current.set(marker.id, { marker: placed, host });
      }
      setHosts((before) => {
        const next = new Map([...live.current].map(([id, entry]) => [id, entry.host] as const));
        const same = next.size === before.size && [...next].every(([id, host]) => before.get(id) === host);
        return same ? before : next;
      });
    });
    return () => {
      cancelled = true;
    };
  }, [markers, ready]);

  return (
    <div className={styles.frame} data-el="ADV-MAP-TILES">
      <div ref={container} className={styles.frame} role="application" aria-label={`Zoomable map. ${ATTRIBUTION}`} />
      {ready ? null : <MapPlaceholder fit={fit} />}
      {markers.map((marker) => {
        const host = hosts.get(marker.id);
        return host === undefined ? null : createPortal(marker.node, host, marker.id);
      })}
    </div>
  );
}
