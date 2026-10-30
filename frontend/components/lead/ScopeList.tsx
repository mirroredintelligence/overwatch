'use client';

import { useEffect, useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { bffGet } from '@/lib/bff/client';
import { canInvite, categoryLabel, flagLabel, parseScopeList, stateLabel } from '@/lib/registration/model';
import type { ScopeEntry } from '@/lib/registration/types';
import { AddScopeForm } from './AddScopeForm';
import styles from './lead.module.css';

// The services that may be invited (W28, ui-screens ApprovalWeb1 screen 1). The list is the only
// place an invitation can start from, so only an in-pilot service not yet invited shows Invite.

export function ScopeList() {
  const [entries, setEntries] = useState<ScopeEntry[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [adding, setAdding] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let current = true;
    void (async () => {
      const result = await bffGet('/api/bff/scope', parseScopeList);
      if (!current) return;
      if (result.ok) {
        setEntries(result.data.entries);
        setFailed(false);
      } else {
        setFailed(true);
      }
    })();
    return () => {
      current = false;
    };
  }, [version]);

  const added = (name: string) => {
    setAdding(false);
    setNotice(`Added ${name} to the scope list.`);
    setVersion((n) => n + 1);
  };

  return (
    <main className={styles.page}>
      <h1 className={styles.heading}>Services in scope</h1>
      <p className={styles.lede}>You can only invite services on this list.</p>

      {notice !== null ? <p role="status">{notice}</p> : null}
      {failed ? <Banner tone="warning" title="The scope list could not be loaded. Try again shortly." /> : null}

      {entries !== null ? (
        <ul className={styles.list} aria-label="Services in scope">
          {entries.map((entry) => (
            <li key={entry.serviceId} className={styles.card} data-el="LEAD-SCOPE-ROW">
              <p className={styles.name}>{entry.name}</p>
              <p className={styles.meta}>{categoryLabel(entry.category)}</p>
              <p className={styles.meta}>
                <span className={styles.tag}>{flagLabel(entry.flag)}</span>
                <span>{stateLabel(entry.registrationState)}</span>
              </p>
              {canInvite(entry) ? (
                <div>
                  <Button
                    variant="secondary"
                    href={`/lead/reporters/invite?service=${encodeURIComponent(entry.serviceId)}`}
                    dataEl="LEAD-SCOPE-INVITE-LINK"
                  >
                    Invite
                  </Button>
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}

      {adding ? (
        <AddScopeForm onAdded={added} onCancel={() => setAdding(false)} />
      ) : (
        <Button variant="secondary" dataEl="LEAD-SCOPE-ADD-BTN" onClick={() => setAdding(true)}>
          Add a service to the scope list
        </Button>
      )}
    </main>
  );
}
