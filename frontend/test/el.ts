// Finds an element by its stable data-el id (docs/design/network-ui.md section 10). Throws when the
// id is missing, so a test names the element it needs rather than passing on an empty result.
export function byEl(id: string, root: ParentNode = document.body): HTMLElement {
  const found = root.querySelector<HTMLElement>(`[data-el="${id}"]`);
  if (!found) throw new Error(`no element with data-el ${id}`);
  return found;
}
