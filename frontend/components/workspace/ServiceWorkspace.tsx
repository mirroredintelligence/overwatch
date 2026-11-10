'use client';

import { useEffect, useState } from 'react';
import { ServiceDetail } from '@/components/service/ServiceDetail';
import type { DialogContext } from '@/lib/workspace/dialog';
import { workspaceHref } from '@/lib/workspace/url';
import { ServiceActions } from './ServiceActions';
import { ServiceCheck } from './ServiceCheck';
import { WorkspacePage } from './WorkspacePage';
import { useWorkspace } from './WorkspaceProvider';

// The service page inside the workspace (DEC-1376, WS-SVC): the frame around the existing service detail, and the
// assistant's turn for the service. The effect depends only on primitives, so a re-render never revisits the turn.
// Note: the service turn fills its echo ("Open {serviceName}") before choosing a reply, so a visit with an empty
// context throws when the thread already has entries. This page only visits empty when nothing is opened.

export function ServiceWorkspace({ serviceId }: { serviceId: string }) {
  const { opened, visit, criteriaComplete, show } = useWorkspace();
  const [checking, setChecking] = useState(false);
  // Whether criteria were set when the page opened. It is not followed afterwards: entering a patient's details in the
  // check must not make the assistant revisit the service turn and repeat itself.
  const [criteriaSet] = useState(criteriaComplete);
  const isOpen = opened !== null;
  const serviceName = opened?.serviceName;
  const updated = opened?.updated;
  const stale = opened?.stale;
  const noReport = opened?.noReport;

  useEffect(() => {
    const context: DialogContext = isOpen ? { serviceName, updated, stale, noReport, criteriaSet } : { criteriaSet };
    visit('advisor.service', context);
  }, [visit, isOpen, serviceName, updated, stale, noReport, criteriaSet]);

  const backHref = workspaceHref('advisor.results');
  // "Book a slot" opens the check in the thread (shown again if the person had hidden it).
  const openCheck = () => {
    show();
    setChecking(true);
  };
  const card = checking ? <ServiceCheck serviceId={serviceId} onClose={() => setChecking(false)} /> : undefined;
  return (
    <WorkspacePage title="Service detail" backHref={backHref} withThread card={card}>
      <ServiceDetail
        serviceId={serviceId}
        backHref={backHref}
        backLabel="Back to results"
        rootLabel="Find a service"
        tabbed
        actions={<ServiceActions serviceId={serviceId} onCheck={openCheck} />}
      />
    </WorkspacePage>
  );
}
