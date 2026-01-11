import { useState } from 'react';
import { getConfig } from '../../config';

interface TestProviderProps {
  providerName: string;
  onClose: () => void;
}

interface TestResult {
  success: boolean;
  message: string;
  latency?: number;
  timestamp: string;
}

const TestProvider = ({ providerName, onClose }: TestProviderProps) => {
  const [testing, setTesting] = useState(false);
  const [testMessage, setTestMessage] = useState('');
  const [testResults, setTestResults] = useState<TestResult[]>([]);

  const handleTest = async () => {
    if (!testMessage.trim()) {
      alert('Please enter a test message');
      return;
    }

    setTesting(true);
    try {
      const config = getConfig();
      const baseUrl = config.nlTpsApiUrl.replace('/v1', '');
      const url = `${baseUrl}/api/llm/providers/${providerName}/test`;
      const startTime = Date.now();
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: testMessage }),
      });

      const latency = Date.now() - startTime;
      const data = await response.json();

      const result: TestResult = {
        success: response.ok,
        message: data.message || data.error || 'Test completed',
        latency,
        timestamp: new Date().toLocaleTimeString(),
      };

      setTestResults((prev) => [result, ...prev]);
      if (response.ok) {
        setTestMessage('');
      }
    } catch (error) {
      const result: TestResult = {
        success: false,
        message: error instanceof Error ? error.message : 'Test failed',
        timestamp: new Date().toLocaleTimeString(),
      };
      setTestResults((prev) => [result, ...prev]);
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-bold text-slate-800 mb-2">
          Test Provider: {providerName}
        </h3>
        <p className="text-sm text-slate-600">
          Send a test message to verify the provider connection
        </p>
      </div>

      {/* Input Area */}
      <div className="space-y-3">
        <textarea
          value={testMessage}
          onChange={(e) => setTestMessage(e.target.value)}
          placeholder="Enter a test message..."
          rows={4}
          className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
        />
        <div className="flex gap-2">
          <button
            onClick={handleTest}
            disabled={testing}
            className="px-4 py-2 bg-amber-500 text-white font-medium rounded-lg hover:bg-amber-600 transition disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {testing ? 'Testing...' : 'Send Test'}
          </button>
          <button
            onClick={onClose}
            className="px-4 py-2 bg-slate-300 text-slate-800 font-medium rounded-lg hover:bg-slate-400 transition"
          >
            Close
          </button>
        </div>
      </div>

      {/* Results */}
      {testResults.length > 0 && (
        <div className="space-y-3">
          <h4 className="font-semibold text-slate-800">Test Results</h4>
          <div className="space-y-2 max-h-96 overflow-y-auto">
            {testResults.map((result, index) => (
              <div
                key={index}
                className={`p-4 rounded-lg border-l-4 ${
                  result.success
                    ? 'bg-green-50 border-l-green-500'
                    : 'bg-red-50 border-l-red-500'
                }`}
              >
                <div className="flex items-start justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className={`text-lg ${result.success ? '✓' : '✗'}`}>
                      {result.success ? '✓' : '✗'}
                    </span>
                    <span className={`font-medium ${
                      result.success ? 'text-green-800' : 'text-red-800'
                    }`}>
                      {result.success ? 'Success' : 'Failed'}
                    </span>
                  </div>
                  <span className="text-xs text-slate-600">{result.timestamp}</span>
                </div>
                <p className={`text-sm mb-2 ${
                  result.success ? 'text-green-700' : 'text-red-700'
                }`}>
                  {result.message}
                </p>
                {result.latency && (
                  <p className="text-xs text-slate-600">
                    Latency: {result.latency}ms
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {testResults.length === 0 && (
        <div className="p-6 bg-slate-50 rounded-lg text-center text-slate-600">
          <p>No test results yet. Send a test message above to get started.</p>
        </div>
      )}
    </div>
  );
};

export default TestProvider;
