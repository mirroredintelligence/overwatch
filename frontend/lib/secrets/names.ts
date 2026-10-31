// The name rule of DEC-1304, the same as the back end's. Key Vault allows letters, digits and hyphens up
// to 127 characters; the rule is tighter so that two names can never collide and nothing but a plain
// word reaches the vault's address: lower-case letters and digits in runs joined by single hyphens.
// The secrets of the web tier have no `/`, so a name is used as it is.

const NAME = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const MAX_LENGTH = 127;

export function isSecretName(value: unknown): value is string {
  return typeof value === 'string' && value.length <= MAX_LENGTH && NAME.test(value);
}
