import React from 'react';
import { FormField } from '../../types/bpmn';
import PermissionRuleEditor from './PermissionRuleEditor';
import TaskBindingEditor from './TaskBindingEditor';

interface FieldPropertiesPanelProps {
  field: FormField;
  onUpdate: (updates: Partial<FormField>) => void;
  bpmnXml?: string;
}

const FieldPropertiesPanel: React.FC<FieldPropertiesPanelProps> = ({
  field,
  onUpdate,
  bpmnXml,
}) => {
  return (
    <div className="w-80 bg-white border-l border-gray-300 p-4 overflow-y-auto max-h-screen">
      <h3 className="text-lg font-semibold mb-4">Field Properties</h3>

      {/* Field Name */}
      <div className="mb-4">
        <label className="block text-sm font-medium text-gray-700">
          Field Name
        </label>
        <input
          type="text"
          value={field.name}
          onChange={(e) => onUpdate({ name: e.target.value })}
          className="mt-1 w-full px-3 py-2 border border-gray-300 rounded-md"
        />
      </div>

      {/* Label */}
      <div className="mb-4">
        <label className="block text-sm font-medium text-gray-700">
          Label
        </label>
        <input
          type="text"
          value={field.label}
          onChange={(e) => onUpdate({ label: e.target.value })}
          className="mt-1 w-full px-3 py-2 border border-gray-300 rounded-md"
        />
      </div>

      {/* Type */}
      <div className="mb-4">
        <label className="block text-sm font-medium text-gray-700">Type</label>
        <select
          value={field.type}
          onChange={(e) => onUpdate({ type: e.target.value as any })}
          className="mt-1 w-full px-3 py-2 border border-gray-300 rounded-md"
        >
          <option value="text">Text</option>
          <option value="number">Number</option>
          <option value="date">Date</option>
          <option value="select">Select</option>
          <option value="checkbox">Checkbox</option>
          <option value="file">File</option>
        </select>
      </div>

      {/* Required */}
      <div className="mb-4">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={field.required}
            onChange={(e) => onUpdate({ required: e.target.checked })}
          />
          <span className="text-sm font-medium text-gray-700">Required</span>
        </label>
      </div>

      {/* Permission Rules */}
      <div className="mb-4 pt-4 border-t border-gray-200">
        <h4 className="text-sm font-medium text-gray-700 mb-2">
          Permission Rules
        </h4>
        <PermissionRuleEditor
          permissions={field.permissions || []}
          onChange={(permissions) => onUpdate({ permissions })}
        />
      </div>

      {/* Task Binding */}
      {bpmnXml && (
        <div className="mb-4 pt-4 border-t border-gray-200">
          <h4 className="text-sm font-medium text-gray-700 mb-2">
            Task Binding
          </h4>
          <TaskBindingEditor
            bpmnXml={bpmnXml}
            currentBinding={field.taskBinding || ''}
            onBindingChange={(taskId) => onUpdate({ taskBinding: taskId })}
          />
        </div>
      )}
    </div>
  );
};

export default FieldPropertiesPanel;
