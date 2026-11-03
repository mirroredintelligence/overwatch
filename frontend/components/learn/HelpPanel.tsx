import { Button } from '@/components/ui/Button';
import { telHref } from '@/lib/exec/call';
import layout from './Learn.module.css';

// "Need a hand?" (W53, TrainingPhone screen 4). The coordination team number comes from the service's own
// record, never from a constant: with no number set, the panel says so rather than showing one. A number
// that is set is selectable text and a phone link. No separate one-page guide is written (DEC-721 item 1),
// so the guide link goes to the help page.

export function HelpPanel({ spoaPhone, champion }: { spoaPhone: string | null; champion?: string }) {
  return (
    <section className={layout.helpCard} aria-labelledby="help-heading">
      <h2 id="help-heading" className={layout.helpHeading}>Need a hand?</h2>
      <ul className={layout.ways} aria-label="Ways to get help">
        <li>
          <Button variant="secondary" href="/help" dataEl="HELP-GUIDE-LINK">Read the one-page guide</Button>
        </li>
        <li className={layout.way}>Ask your champion{champion ? `, ${champion}` : ''}</li>
        <li className={layout.way}>
          Phone the shift lead:{' '}
          {spoaPhone !== null ? (
            <a href={telHref(spoaPhone)} data-el="HELP-PHONE-LINK">{spoaPhone}</a>
          ) : (
            <span>The number is not set for your service yet. Ask your shift lead.</span>
          )}
        </li>
        <li>
          <Button variant="secondary" href="/help/problem" dataEl="HELP-REPORT-LINK">Report a problem</Button>
        </li>
      </ul>
      <p className={layout.helpNote}>Help is one tap away on every screen.</p>
    </section>
  );
}
