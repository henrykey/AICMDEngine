import axios from 'axios';
import { getConfig } from '../config';

// Create instances without config first, relying on interceptors to set baseURL
// This ensures we always read the *loaded* config, not the initial default import.

export const api = axios.create();

api.interceptors.request.use((reqConfig) => {
    // Set baseURL dynamically from the loaded config
    reqConfig.baseURL = getConfig().nlTpsApiUrl;

    const token = localStorage.getItem('token');
    const tenantId = localStorage.getItem('tenantId');

    if (token) {
        reqConfig.headers['Authorization'] = `Bearer ${token}`;
    }

    if (tenantId) {
        reqConfig.headers['X-Tenant-ID'] = tenantId;
    }

    return reqConfig;
});

// Membership Service Client for login only
export const membershipApi = axios.create();

membershipApi.interceptors.request.use((reqConfig) => {
    // Set baseURL dynamically from the loaded config
    const config = getConfig();
    if (config.membershipApiUrl) {
        reqConfig.baseURL = config.membershipApiUrl;
    }

    const token = localStorage.getItem('token');
    if (token) {
        reqConfig.headers['Authorization'] = `Bearer ${token}`;
    }
    return reqConfig;
});
