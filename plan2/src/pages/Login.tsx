import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../lib/api';
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
            const tenantId = localStorage.getItem('tenantId') || '1';

            // Call NL-TPS auth endpoint (which will delegate to Membership or other auth backend)
            const res = await api.post('/auth/login', {
                username,
                password,
                device_id: 'plan2-admin-01'
            }, {
                headers: {
                    'X-Tenant-ID': tenantId
                }
            });

            // Robust token extraction
            const token = res.data.access_token || res.data.token || res.data.data?.token;

            if (!token) {
                throw new Error("No access token returned from Membership Service");
            }

            localStorage.setItem('token', token);
            localStorage.setItem('username', username);

            // Default tenant check - must match database tenant_id (integer 1)
            if (!localStorage.getItem('tenantId')) {
                localStorage.setItem('tenantId', '1');
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

                    <button
                        type="submit"
                        disabled={isLoading}
                        className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-medium py-2.5 rounded-lg transition mt-6"
                    >
                        {isLoading ? 'Signing in...' : 'Sign In'}
                    </button>

                    <div className="text-xs text-center text-slate-500 mt-4">
                        Connecting to: {getConfig().nlTpsApiUrl || 'NL-TPS Service'}
                    </div>
                </form>
            </div>
        </div>
    );
}
