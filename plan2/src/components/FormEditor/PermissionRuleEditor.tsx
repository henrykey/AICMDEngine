import React, { useState } from 'react';
import { PermissionRule } from '../../types/bpmn';

interface PermissionRuleEditorProps {
  permissions: PermissionRule[];
  onChange: (permissions: PermissionRule[]) => void;
}

const PermissionRuleEditor: React.FC<PermissionRuleEditorProps> = ({
  permissions = [],
  onChange,
}) => {
  const [newRule, setNewRule] = useState<PermissionRule>({
    action: 'view',
    subjects: [],
  });

  const handleAddRule = () => {
    if (newRule.subjects.length > 0) {
      onChange([...permissions, { ...newRule }]);
      setNewRule({ action: 'view', subjects: [] });
    }
  };

  const handleRemoveRule = (index: number) => {
    onChange(permissions.filter((_, i) => i !== index));
  };

  return (
    <div className="space-y-3">
      {/* Existing Rules */}
      {permissions.map((rule, index) => (
        <div key={index} className="p-2 bg-gray-50 rounded border border-gray-200">
          <div className="flex items-center justify-between mb-1">
            <span className="text-sm font-medium">{rule.action}</span>
            <button
              onClick={() => handleRemoveRule(index)}
              className="text-red-600 hover:bg-red-100 px-2 py-1 rounded text-xs"
            >
              Remove
            </button>
          </div>
          <div className="text-xs text-gray-600">
            {rule.subjects.join(', ')}
          </div>
        </div>
      ))}

      {/* Add New Rule */}
      <div className="p-2 bg-blue-50 rounded border border-blue-200">
        <div className="mb-2">
          <select
            value={newRule.action}
            onChange={(e) =>
              setNewRule({ ...newRule, action: e.target.value as any })
            }
            className="w-full px-2 py-1 text-sm border border-blue-300 rounded"
          >
            <option value="view">View</option>
            <option value="edit">Edit</option>
            <option value="hide">Hide</option>
          </select>
        </div>

        <div className="mb-2">
          <input
            type="text"
            placeholder="e.g., role:approver or org:finance"
            value={newRule.subjects.join(', ')}
            onChange={(e) =>
              setNewRule({
                ...newRule,
                subjects: e.target.value
                  .split(',')
                  .map((s) => s.trim())
                  .filter((s) => s),
              })
            }
            className="w-full px-2 py-1 text-sm border border-blue-300 rounded"
          />
        </div>

        <button
          onClick={handleAddRule}
          className="w-full px-2 py-1 text-sm bg-blue-500 text-white rounded hover:bg-blue-600"
        >
          Add Rule
        </button>
      </div>

      <p className="text-xs text-gray-500 mt-2">
        Format: role:name, org:name, or member:id
      </p>
    </div>
  );
};

export default PermissionRuleEditor;
