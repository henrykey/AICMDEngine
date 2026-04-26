export interface AppConfig {
    nlTpsApiUrl: string;
    membershipApiUrl?: string;
    membershipLoginPath?: string;
    membershipSwitchTenantPath?: string;
    membershipUserPath?: string;
}

// Default config matches the JSON structure but serves as fallback.
// membershipApiUrl is intentionally empty so all /v2/* requests use
// relative paths and are handled by the nginx reverse proxy. This
// ensures the app works correctly even if config.json fails to load
// (e.g. when accessed via a reverse-proxy bridge).
let config: AppConfig = {
    nlTpsApiUrl: '/v1',
    membershipApiUrl: '',
    membershipLoginPath: '/v2/auth/unified/login',
    membershipSwitchTenantPath: '/v2/auth/unified/switch-tenant'
};

export const loadConfig = async (): Promise<void> => {
    try {
        const response = await fetch('/config.json');
        if (!response.ok) {
            throw new Error(`Failed to load config: ${response.statusText}`);
        }
        const runtimeConfig = await response.json();

        // Merge runtime config into the config object
        config = { ...config, ...runtimeConfig };
        console.log('Runtime config loaded:', config);
    } catch (error) {
        console.error('Could not load runtime config, using defaults.', error);
    }
};

// Accessor to get the loaded config
export const getConfig = (): AppConfig => config;

// Backward compatibility export if needed, or purely use accessors
export { config };
