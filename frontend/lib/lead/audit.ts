// The audit replay as the BFF gives it (W47): what the advisor saw at the decision, for one case reference.

export type ReplayShown = { serviceName: string; status: string; value: string; age: string };
export type ReplayCriteria = { serviceName: string; version: number };
export type ReplayTimelineItem = { at: string; label: string };

export type AuditReplay = {
  reference: string;
  decisionAt: string;
  chainOk: boolean;
  shown: ReplayShown[];
  criteriaVersions: ReplayCriteria[];
  timeline: ReplayTimelineItem[];
};
