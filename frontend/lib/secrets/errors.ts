// The two ways a secret read fails. Both are faults for the caller (a thrown error, so a 5xx at the BFF
// seam), never "no session" and never a pass. A message names the secret or the variable and never a
// value, and no error carries the vault's own text, because that text is not ours to vouch for.

/** The secret is not there: unknown to the vault, unset in the environment, or a name the rule refuses. */
export class SecretNotFoundError extends Error {
  constructor(name?: string, variable?: string) {
    super(
      name === undefined
        ? 'The secret name is not valid.'
        : `The secret ${name} was not found${variable === undefined ? '' : `: ${variable} is not set`}.`,
    );
    this.name = 'SecretNotFoundError';
  }
}

/** The secret cannot be read, or the configuration that says where to read it is wrong. */
export class SecretConfigurationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'SecretConfigurationError';
  }
}
