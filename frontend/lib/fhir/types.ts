// Minimal FHIR R4B types for the BFF. Hand-written and small: later tasks
// extend them when they need more of a resource. These describe shape only;
// they do not validate. Validation is the back end's job (R14).

export type Resource = {
  resourceType: string;
  id?: string;
  meta?: {
    versionId?: string;
    lastUpdated?: string;
    security?: Coding[];
    tag?: Coding[];
  };
  [key: string]: unknown;
};

export type Coding = {
  system?: string;
  code?: string;
  display?: string;
  version?: string;
  userSelected?: boolean;
};

export type CodeableConcept = {
  coding?: Coding[];
  text?: string;
};

export type Reference = {
  reference?: string;
  type?: string;
  display?: string;
};

export type OperationOutcomeIssue = {
  severity: 'fatal' | 'error' | 'warning' | 'information';
  code: string;
  diagnostics?: string;
  expression?: string[];
};

export type OperationOutcome = {
  resourceType: 'OperationOutcome';
  issue: OperationOutcomeIssue[];
};

export type ParameterValue = {
  valueString?: string;
  valueBoolean?: boolean;
  valueInteger?: number;
  valueDecimal?: number;
  valueDateTime?: string;
  valueCode?: string;
  valueReference?: Reference;
  valueCodeableConcept?: CodeableConcept;
};

export type ParametersParameter = ParameterValue & {
  name: string;
  part?: ParametersParameter[];
};

export type Parameters = {
  resourceType: 'Parameters';
  parameter?: ParametersParameter[];
};

export type BundleEntry<T extends Resource = Resource> = {
  resource?: T;
  fullUrl?: string;
};

export type Bundle<T extends Resource = Resource> = {
  resourceType: 'Bundle';
  type: string;
  total?: number;
  entry?: BundleEntry<T>[];
};
