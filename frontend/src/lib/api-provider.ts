/**
 * Integration placeholder only. No HTTP routes or backend contracts are assumed.
 *
 * Implement MeshMindDataProvider when Control's task creation, status/event,
 * session history, validated result, report download, and bounded worker retry
 * contracts are agreed. Map those responses to types.ts; do not import mock
 * measurements into the adapter. Select the adapter in data-provider.ts.
 *
 * Confirm: authentication/CORS, event ordering and reconnect behavior, the
 * distinction between unavailable and invalid evidence, retry semantics that
 * preserve independent valid work, and backend-provided report URLs.
 */
export {};
