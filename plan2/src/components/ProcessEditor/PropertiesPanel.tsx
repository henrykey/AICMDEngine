import React, { useState, useEffect } from 'react';
import ExecutorConfigEditor from './ExecutorConfigEditor';

interface PropertiesPanelProps {
  element: any;
  onPropertyChange: (property: string, value: any) => void;
}

const PropertiesPanel: React.FC<PropertiesPanelProps> = ({
  element,
  onPropertyChange,
}) => {
  const [name, setName] = useState(element?.businessObject?.name || '');
  const [executorPattern, setExecutorPattern] = useState(
    element?.businessObject?.documentation?.[0]?.text
  );

  useEffect(() => {
    setName(element?.businessObject?.name || '');
  }, [element?.id]);

  if (!element) {
    return (
      <div className="p-4 text-gray-500">
        Select an element to view properties
      </div>
    );
  }

  const handleNameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newName = e.target.value;
    setName(newName);
    onPropertyChange('name', newName);
  };

  const handleExecutorChange = (config: any) => {
    setExecutorPattern(config);
    onPropertyChange('executorPattern', config);
  };

  const isUserTask = element.type === 'bpmn:UserTask';

  return (
    <div className="w-80 bg-white border-l border-gray-300 p-4 overflow-y-auto max-h-screen">
      <h3 className="text-lg font-semibold mb-4">Properties</h3>

      {/* Element ID */}
      <div className="mb-4">
        <label className="block text-sm font-medium text-gray-700">ID</label>
        <input
          type="text"
          disabled
          value={element.id}
          className="mt-1 w-full px-3 py-2 border border-gray-300 rounded-md bg-gray-50"
        />
      </div>

      {/* Element Name */}
      <div className="mb-4">
        <label className="block text-sm font-medium text-gray-700">Name</label>
        <input
          type="text"
          value={name}
          onChange={handleNameChange}
          className="mt-1 w-full px-3 py-2 border border-gray-300 rounded-md"
        />
      </div>

      {/* Executor Pattern (only for user tasks) */}
      {isUserTask && (
        <div className="mb-4">
          <h4 className="text-sm font-medium text-gray-700 mb-2">Executor Pattern</h4>
          <ExecutorConfigEditor
            config={executorPattern}
            onChange={handleExecutorChange}
          />
        </div>
      )}
    </div>
  );
};

export default PropertiesPanel;
