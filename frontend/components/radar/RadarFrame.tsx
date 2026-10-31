'use client';

import { type ReactNode, useState } from 'react';
import { AskClinicalPanel } from '@/components/advisor/AskClinicalPanel';
import { NoServiceFits } from '@/components/advisor/NoServiceFits';
import { OutOfArea, PostcodeNotFound } from '@/components/advisor/PostcodeStates';
import { Button } from '@/components/ui/Button';
import type { CaseView } from '@/lib/advisor/codes';
import { canChangePostcode, changePostcode, type PostcodeChange } from '@/lib/advisor/postcodeChange';
import type { OptionsParts } from '@/lib/advisor/options';
import { useCaseOptions } from '@/lib/radar/useCaseOptions';
import { RadarTabs, type RadarView } from './RadarTabs';
import styles from './radar.module.css';

// What every radar screen has in common (RadarWeb 1, 2, 6): the read of the case's options, the loading and
// failed states, the three states that have no radar to draw (postcode not found, outside every service's
// area, no service fits), and the tabs. A state with no radar still names a next step: the call is never
// left at a dead end (W16, W50).

export type RadarContext = {
  parts: OptionsParts;
  /** The case's district, or "this patient" when it has none: for headings. */
  place: string;
  view: CaseView | null;
};

export function RadarFrame({
  caseId,
  current,
  children,
}: {
  caseId: string;
  current: RadarView;
  children: (context: RadarContext) => ReactNode;
}) {
  const { load, retry, choose } = useCaseOptions(caseId);
  const [asking, setAsking] = useState(false);

  if (load.kind === 'loading') return <p role="status">Loading the radar.</p>;
  if (load.kind === 'failed') {
    return (
      <div className={styles.screen}>
        <p role="alert">The radar could not be read. Try again.</p>
        <div className={styles.actions}>
          <Button variant="secondary" onClick={retry} dataEl="RADAR-RETRY-BTN">
            Try again
          </Button>
        </div>
      </div>
    );
  }

  const { parts, postcode, view } = load;
  const searchAgain = async (typed: string): Promise<PostcodeChange> => {
    if (view === null) return 'failed';
    const result = await changePostcode(view, typed);
    if (result === 'saved') retry();
    return result;
  };
  const ask = asking ? <AskClinicalPanel caseRef={caseId} optionsShown={0} onClose={() => setAsking(false)} /> : null;
  const tabs = <RadarTabs caseId={caseId} current={current} />;

  if (parts.notFound) {
    return (
      <div className={styles.screen}>
        {tabs}
        <PostcodeNotFound
          caseId={caseId}
          onAskClinical={() => setAsking(true)}
          districts={parts.districts}
          onChooseDistrict={choose}
          onSearchAgain={canChangePostcode(view) ? searchAgain : undefined}
        />
        {ask}
      </div>
    );
  }
  if (parts.outOfArea) {
    return (
      <div className={styles.screen}>
        {tabs}
        <OutOfArea caseId={caseId} postcode={postcode ?? 'This postcode'} onAskClinical={() => setAsking(true)} districts={parts.districts} onChooseDistrict={choose} />
        {ask}
      </div>
    );
  }
  if (parts.options.length === 0) {
    return (
      <div className={styles.screen}>
        {tabs}
        <NoServiceFits caseId={caseId} onWidened={retry} onAskClinical={() => setAsking(true)} />
        {ask}
      </div>
    );
  }

  return (
    <div className={styles.screen}>
      {tabs}
      {children({ parts, place: postcode ?? 'this patient', view })}
      {ask}
    </div>
  );
}
