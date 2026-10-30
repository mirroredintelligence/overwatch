'use client';

import { useEffect, useState } from 'react';
import { Chip } from '@/components/ui/Chip';
import {
  RANGES,
  TABS,
  TAB_LABELS,
  type Compare,
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

// The insight page's tabs and range (W49). A tab change asks the BFF for that tab with the range
// that is chosen now. The data is aggregates; no person is shown.

type Data = Record<string, unknown>;

// The back end's answer for each tab, as the page reads it. A missing list is an empty one.
function list<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

export function InsightTabs({ initialTab }: { initialTab: InsightTab }) {
  const [tab, setTab] = useState<InsightTab>(initialTab);
  const [range, setRange] = useState<Range>('7d');
  const [result, setResult] = useState<{ key: string; data: Data | null; error: string | null } | null>(null);
  const [funnelName, setFunnelName] = useState<string | null>(null);
  const requestKey = `${tab}|${range}`;

  useEffect(() => {
    let cancelled = false;
    fetch(`/api/bff/console/insight/${tab}?range=${range}`, { credentials: 'same-origin' })
      .then(async (response) => {
        if (!response.ok) throw new Error('status');
        return (await response.json()) as Data;
      })
      .then((body) => {
        if (!cancelled) setResult({ key: requestKey, data: body, error: null });
      })
      .catch(() => {
        if (!cancelled) setResult({ key: requestKey, data: null, error: 'This view could not be loaded. Try again.' });
      });
    return () => {
      cancelled = true;
    };
  }, [tab, range, requestKey]);

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
            unused={list<string>(data.unused)}
          />
        )}
        {data !== null && tab === 'friction' && <FrictionTab rows={list<FrictionRow>(data.rows)} />}
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
