import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { membershipApi } from '../lib/api';
import { getConfig } from '../config';

export default function Login() {
    const navigate = useNavigate();
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const [isLoading, setIsLoading] = useState(false);

    const handleLogin = async (e: React.FormEvent) => {
        e.preventDefault();
        setIsLoading(true);
        setError('');

        try {
            const config = getConfig(); // Get latest config

            // 1. Login to get Token
            // According to docs/MEMBERSHIP_USAGE_MANUAL.md, X-Tenant-ID is required
            // We use '1' or 'default' as initial tenant for login if not known
            const tenantId = localStorage.getItem('tenantId') || '1';

            const res = await membershipApi.post(config.membershipLoginPath, {
                username,
                password,
                device_id: 'nl-tps-admin-01' // Optional but recommended
            }, {
                headers: {
                    'X-Tenant-ID': tenantId
                }
            });

            // Robust token extraction
            // Robust token extraction
            const token = res.data.access_token || res.data.token || res.data.data?.token;

            if (!token) {
                throw new Error("No access token returned from Membership Service");
            }

            localStorage.setItem('token', token);
            localStorage.setItem('username', username);

            // Default tenant check
            if (!localStorage.getItem('tenantId')) {
                localStorage.setItem('tenantId', 'tenant-dev-001');
            }

            navigate('/');
        } catch (err: any) {
            console.error("Login Error:", err);
            console.error("Response Data:", err.response?.data);
            console.error("Status:", err.response?.status);
            setError(err.response?.data?.message || err.message || 'Login failed');
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <div className="min-h-screen bg-gray-900 flex items-center justify-center text-gray-100">
            <div className="bg-gray-800 p-8 rounded-lg shadow-xl w-full max-w-md border border-gray-700">
                <h1 className="text-2xl font-bold mb-6 text-center bg-gradient-to-r from-blue-400 to-purple-500 bg-clip-text text-transparent">
                    NL-TPS Admin
                </h1>

                {error && (
                    <div className="bg-red-900/50 border border-red-500 text-red-200 text-sm p-3 rounded mb-4">
                        {error}
                    </div>
                )}

                <form onSubmit={handleLogin} className="space-y-4">
                    <div>
                        <label className="block text-sm font-medium mb-1 text-gray-400">Username</label>
                        <input
                            type="text"
                            required
                            className="w-full bg-gray-900 border border-gray-600 rounded p-2 focus:ring-2 focus:ring-blue-500 outline-none transition"
                            value={username}
                            onChange={(e) => setUsername(e.target.value)}
                        />
                    </div>

                    <div>
                        <label className="block text-sm font-medium mb-1 text-gray-400">Password</label>
                        <input
                            type="password"
                            required
                            className="w-full bg-gray-900 border border-gray-600 rounded p-2 focus:ring-2 focus:ring-blue-500 outline-none transition"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                        />
                    </div>

                    <button
                        type="submit"
                        disabled={isLoading}
                        className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-medium py-2 rounded transition mt-4"
                    >
                        {isLoading ? 'Signing in...' : 'Sign In'}
                    </button>

                    <div className="text-xs text-center text-gray-500 mt-4">
                        Connecting to: {getConfig().membershipApiUrl}
                    </div>
                </form>
            </div>
        </div>
    );
}
