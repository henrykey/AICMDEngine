import policy from './provider-thinking.v1.json';

export const thinkingModes = ['default', 'low', 'high', 'disabled'] as const;
export function thinkingCapability(baseUrl = '', model = '') {
  let host = '';
  try { host = new URL(baseUrl).hostname.toLowerCase(); } catch { /* Incomplete form input. */ }
  const rule = policy.rules.find(rule => rule.hosts.some(pattern => host === pattern ||
    (pattern.startsWith('*.') && host.endsWith(pattern.slice(1)) && host !== pattern.slice(2))) &&
    new RegExp(`^(?:${rule.models})$`).test(model.trim().toLowerCase()));
  const profiles = policy.profiles as Record<string, Record<string, unknown>>;
  return {
    modes: rule ? ['default', ...Object.keys(profiles[rule.profile])] : ['default'],
    note: rule?.note ?? 'Unverified endpoint/model: only default is available.',
  };
}
