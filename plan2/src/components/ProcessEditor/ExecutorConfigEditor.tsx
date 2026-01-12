import React, { useState } from 'react';

interface ExecutorConfigEditorProps {
  config?: any;
  onChange: (config: any) => void;
}

const EXECUTOR_PATTERNS = [
  'static',
  'form_driven',
  'dynamic',
  'queue_claim',
  'automation',
];

const ExecutorConfigEditor: React.FC<ExecutorConfigEditorProps> = ({
  config = {},
  onChange,
}) => {
  const [pattern, setPattern] = useState(config.executor_pattern || 'static');

  const handlePatternChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const newPattern = e.target.value;
    setPattern(newPattern);
    onChange({ executor_pattern: newPattern, executor_config: {} });
  };

  return (
    <div className="space-y-3">
      <select
        value={pattern}
        onChange={handlePatternChange}
        className="w-full px-3 py-2 border border-gray-300 rounded-md"
      >
        {EXECUTOR_PATTERNS.map((p) => (
          <option key={p} value={p}>
            {p.replace(/_/g, ' ').toUpperCase()}
          </option>
        ))}
      </select>

      <div className="text-xs text-gray-600 p-2 bg-gray-50 rounded">
        {pattern === 'static' && 'Assign to fixed role or department'}
        {pattern === 'form_driven' && 'Ask user to select executor at start'}
        {pattern === 'dynamic' && 'Route based on data analysis'}
        {pattern === 'queue_claim' && 'First available team member claims'}
        {pattern === 'automation' && 'Automated by MCP tool'}
      </div>
    </div>
  );
};

export default ExecutorConfigEditor;
