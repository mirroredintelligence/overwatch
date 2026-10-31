'use client';

import { useEffect, useState } from 'react';
import { Chip } from '@/components/ui/Chip';
import {
  DEVICES,
  RANGES,
  TABS,
  TAB_LABELS,
  type Compare,
  type Device,
  type FrictionRow,
  type Funnel,
  type InsightTab,
  type Measure,
  type PathRow,
  type PipelineRow,
  type Range,
  type Slow,
  type Vital,
} from '@/lib/console/insight';
import styles from '../Console.module.css';
import { FrictionTab } from './FrictionTab';
import { FunnelsTab } from './FunnelsTab';
import { PathsTab } from './PathsTab';
import { PerformanceTab } from './PerformanceTab';
import { ReleasesTab } from './ReleasesTab';

// The insight page's tabs, range and device (W49, W9F). A change asks the BFF for that tab with the range
// and device that are chosen now. The data is aggregates; no person is shown. Whatever stops the back
// end answering is said as "could not be loaded", never as an empty view.

type Data = Record<string, unknown>;

const NOT_LOADED = 'This view could not be loaded. Try again.';

// The back end's answer for each tab, as the page reads it. A missing list is an empty one.
function list<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

export function InsightTabs({ initialTab }: { initialTab: InsightTab }) {
  const [tab, setTab] = useState<InsightTab>(initialTab);
  const [range, setRange] = useState<Range>('7d');
  const [device, setDevice] = useState<Device | null>(null);
  const [result, setResult] = useState<{ key: string; data: Data | null; error: string | null } | null>(null);
  const [funnelName, setFunnelName] = useState<string | null>(null);
  // The release comparison is of releases, not devices, so it takes no device.
  const deviceFor = tab === 'releases' ? null : device;
  const requestKey = `${tab}|${range}|${deviceFor ?? ''}`;

  useEffect(() => {
    let cancelled = false;
    const query = `range=${range}${deviceFor === null ? '' : `&device=${deviceFor}`}`;
    fetch(`/api/bff/console/insight/${tab}?${query}`, { credentials: 'same-origin' })
      .then(async (response) => {
        if (!response.ok) throw new Error('status');
        return (await response.json()) as Data;
      })
      .then((body) => {
        if (!cancelled) setResult({ key: requestKey, data: body, error: null });
      })
      .catch(() => {
        if (!cancelled) setResult({ key: requestKey, data: null, error: NOT_LOADED });
      });
    return () => {
      cancelled = true;
    };
  }, [tab, range, deviceFor, requestKey]);

  // An answer for a view the person has since left is not shown: the key must match the view now.
  const current = result?.key === requestKey ? result : null;
  const data = current?.data ?? null;
  const error = current?.error ?? null;

  const funnels = list<Funnel>(data?.funnels);
  const chosen = funnels.find((funnel) => funnel.name === funnelName) ?? funnels[0] ?? null;

  return (
    <div className={styles.page}>
      <div role="tablist" aria-label="Insight views" className={styles.chips}>
        {TABS.map((name) => (
          <button
            key={name}
            type="button"
            role="tab"
            id={`tab-${name}`}
            aria-selected={tab === name}
            aria-controls="insight-panel"
            tabIndex={tab === name ? 0 : -1}
            data-el={`CON-INS-TAB-${name.toUpperCase()}`}
            onClick={() => setTab(name)}
            className={styles.tab}
          >
            {TAB_LABELS[name]}
          </button>
        ))}
      </div>
      <div className={styles.chips} role="group" aria-label="Time range">
        {RANGES.map((item) => (
          <Chip
            key={item.value}
            pressed={range === item.value}
            onPressedChange={() => setRange(item.value)}
            dataEl={`CON-INS-RANGE-${item.value.toUpperCase()}`}
          >
            {item.label}
          </Chip>
        ))}
      </div>
      {tab !== 'releases' && (
        <div className={styles.chips} role="group" aria-label="Device">
          <Chip pressed={device === null} onPressedChange={() => setDevice(null)} dataEl="CON-INS-DEVICE-ALL">
            All devices
          </Chip>
          {DEVICES.map((item) => (
            <Chip
              key={item.value}
              pressed={device === item.value}
              onPressedChange={() => setDevice(item.value)}
              dataEl={`CON-INS-DEVICE-${item.value.toUpperCase()}`}
            >
              {item.label}
            </Chip>
          ))}
        </div>
      )}
      <div role="tabpanel" id="insight-panel" aria-labelledby={`tab-${tab}`}>
        {error !== null && <p role="alert" className={styles.alert}>{error}</p>}
        {error === null && data === null && <p className={styles.help}>Loading</p>}
        {data !== null && tab === 'funnels' && (
          <>
            {funnels.length > 1 && (
              <div className={styles.chips} role="group" aria-label="Funnel">
                {funnels.map((funnel) => (
                  <Chip
                    key={funnel.name}
                    pressed={chosen?.name === funnel.name}
                    onPressedChange={() => setFunnelName(funnel.name)}
                    dataEl={`CON-INS-FUNNEL-${funnel.name.toUpperCase()}`}
                  >
                    {funnel.label}
                  </Chip>
                ))}
              </div>
            )}
            <FunnelsTab funnel={chosen} />
          </>
        )}
        {data !== null && tab === 'paths' && (
          <PathsTab
            mostCommon={list<PathRow>(data.mostCommon)}
            uTurns={list<PathRow>(data.uTurns)}
            unused={Array.isArray(data.unused) ? (data.unused as string[]) : null}
          />
        )}
        {data !== null && tab === 'friction' && (
          <FrictionTab
            rows={list<FrictionRow>(data.rows)}
            suppressedGroups={typeof data.suppressedGroups === 'number' ? data.suppressedGroups : 0}
          />
        )}
        {data !== null && tab === 'performance' && (
          <PerformanceTab
            vitals={list<Vital>(data.vitals)}
            slowestRoutes={list<Slow>(data.slowestRoutes)}
            slowestQueries={list<Slow>(data.slowestQueries)}
            promptToBoard={(data.promptToBoard as { systemSeconds: number; humanMinutes: number } | undefined) ?? null}
          />
        )}
        {data !== null && tab === 'releases' && (
          <ReleasesTab
            compare={(data.compare as Compare | undefined) ?? null}
            measures={list<Measure>(data.measures)}
            pipeline={list<PipelineRow>(data.pipeline)}
          />
        )}
      </div>
    </div>
  );
}
