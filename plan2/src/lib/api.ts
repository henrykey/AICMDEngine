import axios from 'axios';
import { getConfig } from '../config';

// Create instances without config first, relying on interceptors to set baseURL
// This ensures we always read the *loaded* config, not the initial default import.

export const api = axios.create();
const refreshApi = axios.create();

const TOKEN_REFRESH_SKEW_MS = 5 * 60 * 1000;

type JwtPayload = {
    exp?: number;
};

type RetriableRequestConfig = typeof api.defaults & {
    _retry?: boolean;
};

function decodeJwtPayload(token: string): JwtPayload | null {
    try {
        const payload = token.split('.')[1];
        if (!payload) {
            return null;
        }
        const normalized = payload.replace(/-/g, '+').replace(/_/g, '/');
        const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, '=');
        return JSON.parse(atob(padded));
    } catch {
        return null;
    }
}

function getTokenExpiryMs(token: string | null): number | null {
    if (!token) {
        return null;
    }
    const payload = decodeJwtPayload(token);
    if (!payload?.exp) {
        return null;
    }
    return payload.exp * 1000;
}

function isTokenExpiringSoon(token: string | null): boolean {
    const expiryMs = getTokenExpiryMs(token);
    if (!expiryMs) {
        return false;
    }
    return expiryMs - Date.now() <= TOKEN_REFRESH_SKEW_MS;
}

function clearAuthStorage() {
    localStorage.removeItem('token');
    localStorage.removeItem('refreshToken');
    localStorage.removeItem('username');
    localStorage.removeItem('tenantId');
}

function redirectToLogin() {
    if (window.location.pathname !== '/login') {
        window.location.href = '/login';
    }
}

let refreshPromise: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
    if (refreshPromise) {
        return refreshPromise;
    }

    refreshPromise = (async () => {
        const refreshToken = localStorage.getItem('refreshToken');
        const tenantId = localStorage.getItem('tenantId');

        if (!refreshToken) {
            return null;
        }

        refreshApi.defaults.baseURL = getConfig().nlTpsApiUrl;

        try {
            const response = await refreshApi.post('/auth/token/refresh', {
                refresh_token: refreshToken
            }, {
                headers: tenantId ? { 'X-Tenant-ID': tenantId } : undefined
            });

            const newAccessToken = response.data.access_token;
            const newRefreshToken = response.data.refresh_token || refreshToken;

            if (!newAccessToken) {
                return null;
            }

            localStorage.setItem('token', newAccessToken);
            localStorage.setItem('refreshToken', newRefreshToken);
            return newAccessToken;
        } catch (error) {
            console.warn('Token refresh failed:', error);
            clearAuthStorage();
            return null;
        } finally {
            refreshPromise = null;
        }
    })();

    return refreshPromise;
}

api.interceptors.request.use(async (reqConfig) => {
    // Set baseURL dynamically from the loaded config
    reqConfig.baseURL = getConfig().nlTpsApiUrl;

    let token = localStorage.getItem('token');
    const tenantId = localStorage.getItem('tenantId');

    if (token && isTokenExpiringSoon(token)) {
        token = await refreshAccessToken();
    }

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
    async (error) => {
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

        const originalRequest = error.config as RetriableRequestConfig | undefined;

        if (error.response?.status === 401 && originalRequest && !originalRequest._retry) {
            originalRequest._retry = true;
            const refreshedToken = await refreshAccessToken();
            if (refreshedToken) {
                originalRequest.headers = originalRequest.headers || {};
                originalRequest.headers['Authorization'] = `Bearer ${refreshedToken}`;
                return api.request(originalRequest);
            }
        }

        // Check for token-related errors (check all 4xx/5xx responses)
        if (error.response) {
            if (errorMessage.includes('token') &&
                (errorMessage.includes('expired') ||
                 errorMessage.includes('refresh') ||
                 errorMessage.includes('login') ||
                 errorMessage.includes('please login'))) {
                console.warn('Token expired detected, redirecting to login');
                // Clear stored credentials
                clearAuthStorage();

                // Redirect to login
                redirectToLogin();
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

export function hasUsableSession(): boolean {
    return Boolean(localStorage.getItem('token') || localStorage.getItem('refreshToken'));
}
