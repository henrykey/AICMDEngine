import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { membershipApi, saveAuthSession } from '../lib/api';
import { getConfig } from '../config';

type TenantOption = {
    tenantId: string;
    tenantName: string;
    isDefault: boolean;
    isPrimary: boolean;
};

type TenantSelectionState = {
    tenants: TenantOption[];
    sessionToken: string;
};

const DEFAULT_TENANT_COOKIE = 'MEMBER_DEFAULT_TENANT_ID';
const DEFAULT_TENANT_MAX_AGE_SECONDS = 30 * 24 * 60 * 60;

function normalizeTenantInfos(tenants: any[] = []): TenantOption[] {
    return tenants.map((tenant) => ({
        tenantId: String(tenant.tenant_id ?? tenant.tenantId ?? tenant.id ?? ''),
        tenantName: tenant.tenant_name ?? tenant.tenantName ?? tenant.name ?? '',
        isDefault: tenant.is_default === true || tenant.isDefault === true,
        isPrimary: tenant.is_primary === true || tenant.isPrimary === true
    })).filter((tenant) => tenant.tenantId);
}

function getRememberedDefaultTenant(): { tenantId: string; tenantName?: string } | null {
    try {
        const cookie = document.cookie
            .split(';')
            .find((item) => item.trim().startsWith(`${DEFAULT_TENANT_COOKIE}=`));
        if (!cookie) {
            return null;
        }
        const rawValue = cookie.split('=')[1];
        if (!rawValue) {
            return null;
        }
        const parsed = JSON.parse(decodeURIComponent(rawValue));
        return parsed?.tenantId ? { tenantId: String(parsed.tenantId), tenantName: parsed.tenantName } : null;
    } catch {
        return null;
    }
}

function setRememberedDefaultTenant(tenant?: TenantOption) {
    if (!tenant?.tenantId) {
        return;
    }
    const value = encodeURIComponent(JSON.stringify({
        tenantId: tenant.tenantId,
        tenantName: tenant.tenantName,
        updatedAt: Date.now()
    }));
    document.cookie = `${DEFAULT_TENANT_COOKIE}=${value}; max-age=${DEFAULT_TENANT_MAX_AGE_SECONDS}; path=/; samesite=strict`;
}

function markRememberedDefaultTenant(tenants: TenantOption[]): TenantOption[] {
    const remembered = getRememberedDefaultTenant();
    if (!remembered?.tenantId) {
        return tenants;
    }
    return tenants.map((tenant) => ({
        ...tenant,
        isDefault: tenant.tenantId === remembered.tenantId || tenant.isDefault
    }));
}

function getUnifiedLoginPath(configuredPath?: string): string {
    if (!configuredPath || configuredPath.endsWith('/auth/login')) {
        return '/v2/auth/unified/login';
    }
    return configuredPath;
}

function getSwitchTenantPath(configuredPath?: string): string {
    return configuredPath || '/v2/auth/unified/switch-tenant';
}

function getPreLoginPath(loginPath: string): string {
    return loginPath.replace(/\/login$/, '/pre-login');
}

export default function Login() {
    const navigate = useNavigate();
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [tenantSelection, setTenantSelection] = useState<TenantSelectionState | null>(null);
    const [selectedTenantId, setSelectedTenantId] = useState('');
    const [rememberTenant, setRememberTenant] = useState(true);
    const [forceTenantSelection, setForceTenantSelection] = useState(false);

    const completeLogin = (responseData: any, fallbackTenantId?: string) => {
        saveAuthSession(username, responseData, fallbackTenantId);
        navigate('/');
    };

    const showTenantSelection = (responseData: any, explicitTenants?: TenantOption[]) => {
        const tenants = explicitTenants || normalizeTenantInfos(responseData.available_tenants ?? responseData.availableTenants);
        const defaultTenant = tenants.find((tenant) => tenant.isDefault || tenant.isPrimary) || tenants[0];
        setTenantSelection({
            tenants,
            sessionToken: responseData.session_token ?? responseData.sessionToken ?? ''
        });
        setSelectedTenantId(defaultTenant?.tenantId || '');
    };

    const performPasswordLogin = async (tenantId?: string, setAsDefault = false, selectedTenant?: TenantOption) => {
        const config = getConfig();
        const loginPath = getUnifiedLoginPath(config.membershipLoginPath);
        const payload: Record<string, unknown> = {
            identifier: username,
            password,
            device_type: 'web',
            device_info: 'plan2-admin'
        };

        if (tenantId) {
            payload.tenant_id = Number(tenantId);
        }
        if (setAsDefault) {
            payload.set_as_default = true;
        }

        const res = await membershipApi.post(loginPath, payload, {
            validateStatus: (status) => status >= 200 && status < 400
        });

        if (res.data?.requires_tenant_selection) {
            showTenantSelection(res.data);
            return;
        }

        if (setAsDefault) {
            setRememberedDefaultTenant(selectedTenant);
        }
        completeLogin(res.data, tenantId);
    };

    const handleLogin = async (e: React.FormEvent) => {
        e.preventDefault();
        setIsLoading(true);
        setError('');

        try {
            const config = getConfig();
            const loginPath = getUnifiedLoginPath(config.membershipLoginPath);
            const preLoginPath = getPreLoginPath(loginPath);

            const preLoginRes = await membershipApi.post(preLoginPath, {
                identifier: username
            });
            const tenants = markRememberedDefaultTenant(
                normalizeTenantInfos(preLoginRes.data?.available_tenants ?? preLoginRes.data?.availableTenants)
            );

            if (preLoginRes.data?.user_exists === false) {
                setError('Login failed');
                return;
            }

            if (tenants.length <= 1) {
                await performPasswordLogin(tenants[0]?.tenantId);
                return;
            }

            const defaultTenant = tenants.find((tenant) => tenant.isDefault || tenant.isPrimary);
            if (!forceTenantSelection && defaultTenant) {
                await performPasswordLogin(defaultTenant.tenantId);
                return;
            }

            showTenantSelection({}, tenants);
        } catch (err: any) {
            console.error("Login Error:", err);
            console.error("Response Data:", err.response?.data);
            console.error("Status:", err.response?.status);
            const responseData = err.response?.data;
            if ((err.response?.status === 300 || responseData?.requires_tenant_selection) && (responseData?.available_tenants || responseData?.availableTenants)) {
                showTenantSelection(responseData);
            } else {
                setError(responseData?.error_message || responseData?.message || err.message || 'Login failed');
            }
        } finally {
            setIsLoading(false);
        }
    };

    const handleTenantConfirm = async (tenantIdOverride?: string) => {
        const tenantId = tenantIdOverride || selectedTenantId;
        if (!tenantSelection || !tenantId) {
            setError('Please select a tenant');
            return;
        }

        setIsLoading(true);
        setError('');

        try {
            if (tenantSelection.sessionToken) {
                const config = getConfig();
                const switchTenantPath = getSwitchTenantPath(config.membershipSwitchTenantPath);
                const res = await membershipApi.post(switchTenantPath, {
                    tenant_id: Number(tenantId),
                    session_token: tenantSelection.sessionToken,
                    set_as_default: rememberTenant
                });

                if (rememberTenant) {
                    setRememberedDefaultTenant(tenantSelection.tenants.find((tenant) => tenant.tenantId === tenantId));
                }
                completeLogin(res.data, tenantId);
            } else {
                await performPasswordLogin(
                    tenantId,
                    rememberTenant,
                    tenantSelection.tenants.find((tenant) => tenant.tenantId === tenantId)
                );
            }
        } catch (err: any) {
            console.error("Tenant Selection Error:", err);
            const responseData = err.response?.data;
            setError(responseData?.error_message || responseData?.message || err.message || 'Tenant selection failed');
        } finally {
            setIsLoading(false);
        }
    };

    const handleBackToLogin = () => {
        setTenantSelection(null);
        setSelectedTenantId('');
        setError('');
    };

    return (
        <div className="min-h-screen bg-slate-50 flex items-center justify-center">
            <div className="bg-white p-8 rounded-xl shadow-lg w-full max-w-md border border-slate-200">
                <h1 className="text-3xl font-bold mb-6 text-center text-blue-600">
                    Plan2
                </h1>
                <p className="text-sm text-slate-600 text-center mb-6">
                    Natural Language Task Planning Service
                </p>

                {error && (
                    <div className="bg-red-50 border border-red-200 text-red-700 text-sm p-3 rounded-lg mb-4">
                        {error}
                    </div>
                )}

                {tenantSelection ? (
                    <div className="space-y-4">
                        <div>
                            <h2 className="text-lg font-semibold text-slate-800">Select Tenant</h2>
                            <p className="text-sm text-slate-600 mt-1">
                                Your account can access multiple tenants. Choose one to continue.
                            </p>
                        </div>

                        <div className="space-y-2 max-h-64 overflow-y-auto">
                            {tenantSelection.tenants.map((tenant) => {
                                const selected = tenant.tenantId === selectedTenantId;
                                return (
                                    <button
                                        key={tenant.tenantId}
                                        type="button"
                                        onClick={() => setSelectedTenantId(tenant.tenantId)}
                                        onDoubleClick={() => handleTenantConfirm(tenant.tenantId)}
                                        className={`w-full text-left border rounded-lg p-3 transition ${
                                            selected
                                                ? 'border-blue-500 bg-blue-50 text-blue-900'
                                                : 'border-slate-200 bg-white text-slate-800 hover:border-blue-300'
                                        }`}
                                    >
                                        <div className="font-medium truncate">{tenant.tenantName || `Tenant ${tenant.tenantId}`}</div>
                                        <div className="text-xs text-slate-500 mt-1">
                                            {tenant.isDefault ? 'Default tenant' : tenant.isPrimary ? 'Primary tenant' : `Tenant ID: ${tenant.tenantId}`}
                                        </div>
                                    </button>
                                );
                            })}
                        </div>

                        <label className="flex items-center gap-2 text-sm text-slate-600">
                            <input
                                type="checkbox"
                                checked={rememberTenant}
                                onChange={(event) => setRememberTenant(event.target.checked)}
                            />
                            Remember this tenant
                        </label>

                        <button
                            type="button"
                            disabled={isLoading || !selectedTenantId}
                            onClick={() => handleTenantConfirm()}
                            className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-medium py-2.5 rounded-lg transition"
                        >
                            {isLoading ? 'Switching tenant...' : 'Continue'}
                        </button>

                        <button
                            type="button"
                            disabled={isLoading}
                            onClick={handleBackToLogin}
                            className="w-full border border-slate-200 hover:bg-slate-50 disabled:opacity-50 text-slate-700 font-medium py-2.5 rounded-lg transition"
                        >
                            Back to login
                        </button>
                    </div>
                ) : (
                    <form onSubmit={handleLogin} className="space-y-4">
                        <div>
                            <label className="block text-sm font-medium mb-1 text-slate-700">Username</label>
                            <input
                                type="text"
                                required
                                placeholder="Enter your username"
                                className="w-full bg-white border border-slate-200 rounded-lg p-2.5 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition"
                                value={username}
                                onChange={(e) => setUsername(e.target.value)}
                            />
                        </div>

                        <div>
                            <label className="block text-sm font-medium mb-1 text-slate-700">Password</label>
                            <input
                                type="password"
                                required
                                placeholder="Enter your password"
                                className="w-full bg-white border border-slate-200 rounded-lg p-2.5 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition"
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                            />
                        </div>

                        <label className="flex items-center gap-2 text-sm text-slate-600">
                            <input
                                type="checkbox"
                                checked={forceTenantSelection}
                                onChange={(event) => setForceTenantSelection(event.target.checked)}
                            />
                            Select tenant for this login
                        </label>

                        <button
                            type="submit"
                            disabled={isLoading}
                            className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-medium py-2.5 rounded-lg transition mt-6"
                        >
                            {isLoading ? 'Signing in...' : 'Sign In'}
                        </button>

                        <div className="text-xs text-center text-slate-500 mt-4">
                            Connecting to: {getConfig().membershipApiUrl || 'Membership Service'}
                        </div>
                    </form>
                )}
            </div>
        </div>
    );
}
