/**
 * Bindings View Component
 *
 * Displays and manages Task-Form bindings
 */

import React from 'react';
import { TaskFormBinding, FormDefinition } from '../../types/workflow';

interface BindingsViewProps {
  bindings: TaskFormBinding[];
  bpmnXml: string;
  forms: FormDefinition[];
  onBindingSelect: (binding: TaskFormBinding | null) => void;
  selectedBinding: TaskFormBinding | null;
  onBindingsChange: (bindings: TaskFormBinding[]) => void;
}

const BindingsView: React.FC<BindingsViewProps> = ({
  bindings,
  bpmnXml,
  forms,
  onBindingSelect,
  selectedBinding,
  onBindingsChange,
}) => {
  // Extract UserTasks from BPMN
  const userTasks = extractUserTasks(bpmnXml);

  // Handle create new binding
  const handleCreateBinding = (taskId: string, taskName: string, formId: string) => {
    const form = forms.find(f => f.formId === formId);
    if (!form) return;

    const newBinding: TaskFormBinding = {
      id: `binding-${Date.now()}`,
      taskId,
      taskName,
      formId,
      formName: form.title,
      permissionSync: {
        enabled: true,
        sourceType: 'executor',
      },
      variableMappings: [],
    };

    onBindingsChange([...bindings, newBinding]);
  };

  // Handle delete binding
  const handleDeleteBinding = (bindingId: string) => {
    onBindingsChange(bindings.filter(b => b.id !== bindingId));
    if (selectedBinding?.id === bindingId) {
      onBindingSelect(null);
    }
  };

  return (
    <div className="h-full flex flex-col bg-gray-50 p-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-gray-800">Task-Form Bindings</h3>
        <span className="text-sm text-gray-500">{bindings.length} bindings</span>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {userTasks.length === 0 ? (
          <div className="text-center text-gray-500 py-12">
            <svg className="w-12 h-12 mx-auto mb-3 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
            </svg>
            <p>No user tasks in workflow</p>
            <p className="text-xs mt-1">Add user tasks in process design to bind forms here</p>
          </div>
        ) : (
          <div className="space-y-3">
            {userTasks.map(task => {
              const binding = bindings.find(b => b.taskId === task.id);
              const isSelected = selectedBinding?.taskId === task.id;

              return (
                <div
                  key={task.id}
                  className={`bg-white rounded-lg border p-4 cursor-pointer transition-all ${
                    isSelected
                      ? 'border-blue-500 ring-2 ring-blue-100'
                      : 'border-gray-200 hover:border-gray-300'
                  }`}
                  onClick={() => binding && onBindingSelect(binding)}
                >
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      {/* Task Info */}
                      <div className="flex items-center gap-2 mb-2">
                        <div className="w-8 h-8 bg-blue-100 rounded flex items-center justify-center">
                          <svg className="w-4 h-4 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                          </svg>
                        </div>
                        <div>
                          <p className="font-medium text-gray-800">{task.name || 'Unnamed Task'}</p>
                          <p className="text-xs text-gray-500">{task.id}</p>
                        </div>
                      </div>

                      {/* Binding Status */}
                      {binding ? (
                        <div className="flex items-center gap-2 mt-3 p-2 bg-green-50 rounded">
                          <svg className="w-4 h-4 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                          </svg>
                          <span className="text-sm text-green-700">Bound to: {binding.formName}</span>
                        </div>
                      ) : (
                        <div className="mt-3">
                          {forms.length > 0 ? (
                            <select
                              className="w-full px-3 py-2 text-sm border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
                              onChange={(e) => {
                                if (e.target.value) {
                                  handleCreateBinding(task.id, task.name || '', e.target.value);
                                }
                              }}
                              defaultValue=""
                              onClick={(e) => e.stopPropagation()}
                            >
                              <option value="">Select a form to bind...</option>
                              {forms.map(form => (
                                <option key={form.formId} value={form.formId}>
                                  {form.title}
                                </option>
                              ))}
                            </select>
                          ) : (
                            <p className="text-sm text-gray-500">
                              Please create a form in form design first
                            </p>
                          )}
                        </div>
                      )}
                    </div>

                    {/* Delete Button */}
                    {binding && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDeleteBinding(binding.id);
                        }}
                        className="p-1 text-gray-400 hover:text-red-500 rounded"
                        title="Unbind"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                        </svg>
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};

// Extract UserTasks from BPMN XML
function extractUserTasks(bpmnXml: string): { id: string; name: string }[] {
  const tasks: { id: string; name: string }[] = [];

  // Simple regex-based extraction (replace with proper XML parsing in production)
  const userTaskRegex = /<bpmn:userTask\s+id="([^"]+)"(?:\s+name="([^"]*)")?/g;
  let match;

  while ((match = userTaskRegex.exec(bpmnXml)) !== null) {
    tasks.push({
      id: match[1],
      name: match[2] || '',
    });
  }

  return tasks;
}

export default BindingsView;
