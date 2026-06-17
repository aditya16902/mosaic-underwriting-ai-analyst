/**
 * Minimal pub/sub so unrelated components can tell the Sidebar's report
 * history to refetch without prop-drilling a callback through App.tsx.
 * Used when a new report is generated (manual or, in future, a live
 * notification of an automated run) so the history list reflects it
 * immediately rather than only on next full page load.
 */

type Listener = () => void;

const listeners = new Set<Listener>();

export function onReportsChanged(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function notifyReportsChanged() {
  listeners.forEach((l) => l());
}
