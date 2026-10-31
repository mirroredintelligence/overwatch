'use client';

import { type FormEvent, useCallback, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import { OptionButton } from '@/components/ui/OptionButton';
import { bffFetch, newIdempotencyKey } from '@/lib/advisor/browser';
import type { OptionsParts } from '@/lib/advisor/options';
import {
  BEST_FIT_REASONS,
  type BestFitCode,
  OUTCOMES,
  type OutcomeCode,
  takesDestination,
  TEXT_OUTCOMES,
  type TextOutcome,
} from '@/lib/advisor/outcome';
import styles from './finish.module.css';

// What happened on the call, and why the best fit was not used (W15). Saving closes the case: the
// outcome is recorded and the postcode and needs are no longer kept on the screen. The back end takes
// the service the patient went to with "accepted and booked" and "redirected", and with no other
// outcome (RecordOutcome.check_destination), so the form asks for it for those two only. The services
// listed are the ones the options read gives for this case.

const SAVE_FAILED = 'The outcome could not be saved. Try again.';

export type OutcomeFormProps = {
  caseId: string;
  /** An outcome named in the address. Shown as text when it is one of the no-chip outcomes. */
  preselect: TextOutcome | null;
  /** Called with the time the close was recorded. */
  onClosed: (closedAt: string) => void;
  /** Called when the service the call went to is chosen (or cleared), so the summary can name it (H-322). */
  onDestinationChange?: (serviceId: string | null) => void;
};

type Chosen = OutcomeCode | TextOutcome | null;
type Services = { kind: 'idle' } | { kind: 'loading' } | { kind: 'ready'; list: { serviceId: string; name: string }[] } | { kind: 'failed' };

export function OutcomeForm({ caseId, preselect, onClosed, onDestinationChange }: OutcomeFormProps) {
  const [outcome, setOutcome] = useState<Chosen>(preselect);
  const [bestFit, setBestFit] = useState<BestFitCode | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [destination, setDestination] = useState<string | null>(null);
  const [services, setServices] = useState<Services>({ kind: 'idle' });
  const textOutcome = preselect !== null ? TEXT_OUTCOMES[preselect] : null;
  const needsDestination = outcome !== null && takesDestination(outcome);

  const readServices = useCallback(async () => {
    setServices({ kind: 'loading' });
    // Only the viewer's own services: the back end refuses a destination that is another organisation's.
    const reply = await bffFetch<OptionsParts>(`/api/bff/cases/${encodeURIComponent(caseId)}/options?only=own`);
    setServices(
      reply.ok
        ? {
            kind: 'ready',
            list: reply.body.options
              .filter((item) => item.network === null)
              .map((item) => ({ serviceId: item.serviceId, name: item.name })),
          }
        : { kind: 'failed' },
    );
  }, [caseId]);

  function chooseDestination(serviceId: string | null) {
    setDestination(serviceId);
    onDestinationChange?.(serviceId);
  }

  function choose(next: OutcomeCode) {
    setOutcome(next);
    if (!takesDestination(next)) chooseDestination(null);
    // The services are read once an outcome needs one, and not again unless the read failed.
    else if (services.kind === 'idle') void readServices();
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (outcome === null || busy || (needsDestination && destination === null)) return;
    setBusy(true);
    setFailed(false);
    const body: Record<string, string> = { outcome };
    if (bestFit !== null) body.bestFitNotUsed = bestFit;
    if (needsDestination && destination !== null) body.destinationServiceId = destination;
    const reply = await bffFetch<{ closedAt: string }>(`/api/bff/cases/${encodeURIComponent(caseId)}/outcome`, {
      method: 'POST',
      body,
      idempotencyKey: newIdempotencyKey(),
    });
    if (reply.ok) {
      onClosed(reply.body.closedAt);
      return;
    }
    setBusy(false);
    setFailed(true);
  }

  return (
    <form className={styles.screen} onSubmit={save} noValidate>
      <fieldset className={styles.group}>
        <legend className={styles.legend}>What happened?</legend>
        {textOutcome !== null ? (
          <p className={styles.text}>{textOutcome}</p>
        ) : (
          <div className={styles.chips}>
            {OUTCOMES.map((item) => (
              <Chip
                key={item.code}
                pressed={outcome === item.code}
                onPressedChange={() => choose(item.code)}
                dataEl={`ADV-FIN-OUTCOME-${item.id}`}
              >
                {item.label}
              </Chip>
            ))}
          </div>
        )}
      </fieldset>

      {needsDestination ? (
        <fieldset className={styles.group}>
          <legend className={styles.legend}>Which service did the call go to?</legend>
          {services.kind === 'loading' || services.kind === 'idle' ? <p className={styles.text}>Loading the services.</p> : null}
          {services.kind === 'failed' ? (
            <>
              <p role="alert" className={styles.error}>
                The services could not be read.
              </p>
              <Button variant="secondary" onClick={() => void readServices()}>
                Try again
              </Button>
            </>
          ) : null}
          {services.kind === 'ready' && services.list.length === 0 ? (
            <p className={styles.text}>No service is listed for this case. Record another outcome, or go back to the options.</p>
          ) : null}
          {services.kind === 'ready' ? (
            <div className={styles.chips}>
              {services.list.map((service) => (
                <OptionButton
                  key={service.serviceId}
                  selected={destination === service.serviceId}
                  onSelect={() => chooseDestination(service.serviceId)}
                >
                  {service.name}
                </OptionButton>
              ))}
            </div>
          ) : null}
        </fieldset>
      ) : null}

      <fieldset className={styles.group}>
        <legend className={styles.legend}>If the best fit was not used, why?</legend>
        <div className={styles.chips}>
          {BEST_FIT_REASONS.map((item) => (
            <Chip
              key={item.code}
              pressed={bestFit === item.code}
              onPressedChange={(on) => setBestFit(on ? item.code : null)}
              dataEl={`ADV-FIN-BEST-${item.id}`}
            >
              {item.label}
            </Chip>
          ))}
        </div>
      </fieldset>

      {failed ? (
        <p role="alert" className={styles.error}>
          {SAVE_FAILED}
        </p>
      ) : null}

      <div className={styles.actions}>
        <Button variant="neutral" href={`/advisor/case/${encodeURIComponent(caseId)}/options`}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" busy={busy} disabled={outcome === null || (needsDestination && destination === null)} dataEl="ADV-FIN-SAVE-BTN">
          Save outcome
        </Button>
      </div>
    </form>
  );
}
