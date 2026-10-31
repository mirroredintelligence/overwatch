'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import { coverSummary, coveringPatient, type Layer, LAYERS } from '@/lib/radar/radar';
import { RadarFrame } from './RadarFrame';
import { RadarMap } from './RadarMap';
import styles from './radar.module.css';

// Radar: who covers this area (RadarWeb 1, from the three-ways canvas). Visiting services are areas, the
// overlap of two is hatched, and the places to go are icons. The patient is at the postcode centre.
// Drive-time rings and traffic are in the design but have no data behind them yet: they are shown as off
// and say so, rather than drawn from nothing.

const NOT_AVAILABLE = ['Drive-time rings', 'Traffic'] as const;

export function RadarScreen({ caseId }: { caseId: string }) {
  const [layers, setLayers] = useState<ReadonlySet<Layer>>(new Set(LAYERS.map((layer) => layer.id)));
  const base = `/advisor/case/${encodeURIComponent(caseId)}`;

  const toggle = (layer: Layer, on: boolean) =>
    setLayers((current) => {
      const next = new Set(current);
      if (on) next.add(layer);
      else next.delete(layer);
      return next;
    });

  return (
    <RadarFrame caseId={caseId} current="radar">
      {({ parts, place }) => {
        const covering = coveringPatient(parts.options, parts.patientArea);
        const unplaced = parts.options.filter((option) => option.position === null && option.coverage === null).length;
        return (
          <section className={styles.screen} aria-label="Radar">
            <h2 className={styles.heading}>{`Who covers ${place}`}</h2>
            <p className={styles.sub}>Visiting services show as areas. Hatched means two cover it. Places you go to show as icons.</p>

            <fieldset className={styles.layers}>
              <legend className={styles.legend}>Layers</legend>
              {LAYERS.map((layer) => (
                <Chip key={layer.id} pressed={layers.has(layer.id)} onPressedChange={(on) => toggle(layer.id, on)} dataEl={`RADAR-LAYER-${layer.id.toUpperCase()}`}>
                  {layer.label}
                </Chip>
              ))}
              {NOT_AVAILABLE.map((label) => (
                <Chip key={label} pressed={false} onPressedChange={() => undefined} disabled>
                  {`${label}: not available yet`}
                </Chip>
              ))}
            </fieldset>

            <RadarMap options={parts.options} patientArea={parts.patientArea} layers={layers} postcode={place} />
            {unplaced === 0 ? null : (
              <p className={styles.note}>{`${unplaced} ${unplaced === 1 ? 'service has' : 'services have'} no place on the picture. The list has every service.`}</p>
            )}

            <p className={styles.summary} role="status" data-el="RADAR-SUMMARY">
              {coverSummary(covering)}
            </p>
            <div className={styles.actions}>
              <Button variant="primary" href={`${base}/compare`} dataEl="RADAR-COMPARE-BTN">
                Compare covering services
              </Button>
              <Button variant="secondary" href={`${base}/ways`} dataEl="RADAR-WAYS-BTN">
                Three ways to meet the need
              </Button>
            </div>
          </section>
        );
      }}
    </RadarFrame>
  );
}
