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

// Response interceptor to handle token expiration errors
api.interceptors.response.use(
    (response) => response,
    (error) => {
        // Get error message from various possible locations
        const errorResponse = error.response?.data;
        const errorMessage = (
            errorResponse?.detail ||
            errorResponse?.error_message ||
            errorResponse?.message ||
            error.message || ''
        ).toLowerCase();

        console.debug('API Error:', {
            status: error.response?.status,
            message: errorMessage
        });

        // Check for token-related errors (check all 4xx/5xx responses)
        if (error.response) {
            if (errorMessage.includes('token') &&
                (errorMessage.includes('expired') ||
                 errorMessage.includes('refresh') ||
                 errorMessage.includes('login') ||
                 errorMessage.includes('please login'))) {
                console.warn('Token expired detected, redirecting to login');
                // Clear stored credentials
                localStorage.removeItem('token');
                localStorage.removeItem('username');
                localStorage.removeItem('tenantId');

                // Redirect to login
                window.location.href = '/login';
                return Promise.reject(error);
            }
        }
        return Promise.reject(error);
    }
);

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
