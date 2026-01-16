/**
 * Properties Panel Component (Slide-out)
 *
 * Displays and edits properties for:
 * - BPMN elements (Process tab)
 * - Form controls (Form tab)
 * - Task-Form bindings (Bindings tab)
 */

import React, { useState } from 'react';
import {
  BpmnElement,
  FormControl,
  TaskFormBinding,
  FormDefinition,
  MembershipEntity,
} from '../../types/workflow';
import MembershipSelectorModal from '../Modals/MembershipSelectorModal';

interface PropertiesPanelProps {
  open: boolean;
  onClose: () => void;
  activeTab: 'process' | 'form' | 'bindings';
  selectedElement: BpmnElement | FormControl | TaskFormBinding | null;
  onPropertyChange: (property: string, value: any) => void;
  bpmnXml: string;
  formDefinition: FormDefinition;
}

const PropertiesPanel: React.FC<PropertiesPanelProps> = ({
  open,
  onClose,
  activeTab,
  selectedElement,
  onPropertyChange,
  bpmnXml: _bpmnXml,
  formDefinition: _formDefinition,
}) => {
  const [membershipModalOpen, setMembershipModalOpen] = useState(false);
  const [membershipModalConfig, setMembershipModalConfig] = useState<{
    mode: 'single' | 'multiple';
    allowedTypes: ('department' | 'role' | 'member')[];
    title: string;
    onConfirm: (selected: MembershipEntity[]) => void;
  } | null>(null);

  // Don't render if not open
  if (!open) return null;

  // Open membership selector
  const openMembershipSelector = (
    config: typeof membershipModalConfig
  ) => {
    setMembershipModalConfig(config);
    setMembershipModalOpen(true);
  };

  // Close membership selector
  const closeMembershipSelector = () => {
    setMembershipModalOpen(false);
    setMembershipModalConfig(null);
  };

  // Handle membership selection
  const handleMembershipConfirm = (selected: MembershipEntity[]) => {
    if (membershipModalConfig?.onConfirm) {
      membershipModalConfig.onConfirm(selected);
    }
    closeMembershipSelector();
  };

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/20 z-40"
        onClick={onClose}
      />

      {/* Panel */}
      <div className="fixed right-0 top-0 h-full w-80 bg-white shadow-xl z-50 flex flex-col animate-slide-in-right">
        {/* Header */}
        <div className="p-4 border-b border-gray-200 flex items-center justify-between">
          <h3 className="font-semibold text-gray-800">Properties</h3>
          <button
            onClick={onClose}
            className="p-1 text-gray-400 hover:text-gray-600 rounded"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4">
          {!selectedElement ? (
            <div className="text-center text-gray-500 py-8">
              <p>Select an Element</p>
              <p className="text-xs mt-1">Click an element on the canvas to view its properties</p>
            </div>
          ) : (
            <>
              {activeTab === 'process' && (
                <ProcessProperties
                  element={selectedElement as BpmnElement}
                  onChange={onPropertyChange}
                  onOpenMembershipSelector={openMembershipSelector}
                />
              )}
              {activeTab === 'form' && (
                <FormControlProperties
                  control={selectedElement as FormControl}
                  onChange={onPropertyChange}
                  onOpenMembershipSelector={openMembershipSelector}
                />
              )}
              {activeTab === 'bindings' && (
                <BindingProperties
                  binding={selectedElement as TaskFormBinding}
                  onChange={onPropertyChange}
                />
              )}
            </>
          )}
        </div>
      </div>

      {/* Membership Selector Modal */}
      {membershipModalConfig && (
        <MembershipSelectorModal
          open={membershipModalOpen}
          onClose={closeMembershipSelector}
          mode={membershipModalConfig.mode}
          allowedTypes={membershipModalConfig.allowedTypes}
          onConfirm={handleMembershipConfirm}
          title={membershipModalConfig.title}
        />
      )}
    </>
  );
};

// Process Element Properties
interface ProcessPropertiesProps {
  element: BpmnElement;
  onChange: (property: string, value: any) => void;
  onOpenMembershipSelector: (config: any) => void;
}

const ProcessProperties: React.FC<ProcessPropertiesProps> = ({
  element,
  onChange,
  onOpenMembershipSelector,
}) => {
  const isUserTask = element.type === 'bpmn:UserTask';
  const [executorValue, setExecutorValue] = useState<string>('');

  return (
    <div className="space-y-4">
      {/* Basic Info */}
      <PropertySection title="Basic Information">
        <PropertyField label="ID">
          <input
            type="text"
            value={element.id}
            disabled
            className="w-full px-3 py-2 text-sm bg-gray-50 border border-gray-200 rounded text-gray-500"
          />
        </PropertyField>
        <PropertyField label="Name">
          <input
            type="text"
            value={element.name || ''}
            onChange={(e) => onChange('name', e.target.value)}
            className="w-full px-3 py-2 text-sm border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="输入名称"
          />
        </PropertyField>
        <PropertyField label="Type">
          <input
            type="text"
            value={element.type.replace('bpmn:', '')}
            disabled
            className="w-full px-3 py-2 text-sm bg-gray-50 border border-gray-200 rounded text-gray-500"
          />
        </PropertyField>
      </PropertySection>

      {/* Executor Config (for UserTask) */}
      {isUserTask && (
        <PropertySection title="Executor Configuration">
          <PropertyField label="Execution Mode">
            <select
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
              defaultValue="static"
            >
              <option value="static">Static Assignment</option>
              <option value="form_driven">Form Driven</option>
              <option value="dynamic">Dynamic Routing</option>
              <option value="queue_claim">Queue Claim</option>
              <option value="automation">Automation</option>
            </select>
          </PropertyField>
          <PropertyField label="Executor">
            <div
              onClick={() => {
                onOpenMembershipSelector({
                  mode: 'single',
                  allowedTypes: ['role', 'department', 'member'],
                  title: 'Select Executor',
                  onConfirm: (selected: MembershipEntity[]) => {
                    if (selected.length > 0) {
                      setExecutorValue(selected[0].name);
                      onChange('executor', selected[0]);
                    }
                  },
                });
              }}
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded cursor-pointer hover:border-blue-500 flex items-center justify-between"
            >
              <span className={executorValue ? 'text-gray-800' : 'text-gray-400'}>
                {executorValue || 'Click to select...'}
              </span>
              <svg className="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 9l4-4 4 4m0 6l-4 4-4-4" />
              </svg>
            </div>
          </PropertyField>
        </PropertySection>
      )}

      {/* Form Binding (for UserTask) */}
      {isUserTask && (
        <PropertySection title="Form Binding">
          <PropertyField label="Bind Form">
            <div className="w-full px-3 py-2 text-sm border border-gray-300 rounded cursor-pointer hover:border-blue-500 flex items-center justify-between">
              <span className="text-gray-400">Click to select form...</span>
              <svg className="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </div>
          </PropertyField>
        </PropertySection>
      )}
    </div>
  );
};

// Form Control Properties
interface FormControlPropertiesProps {
  control: FormControl;
  onChange: (property: string, value: any) => void;
  onOpenMembershipSelector: (config: any) => void;
}

const FormControlProperties: React.FC<FormControlPropertiesProps> = ({
  control,
  onChange,
  onOpenMembershipSelector,
}) => {
  return (
    <div className="space-y-4">
      {/* Basic Info */}
      <PropertySection title="Basic Information">
        <PropertyField label="ID">
          <input
            type="text"
            value={control.id}
            disabled
            className="w-full px-3 py-2 text-sm bg-gray-50 border border-gray-200 rounded text-gray-500"
          />
        </PropertyField>
        <PropertyField label="Label">
          <input
            type="text"
            value={control.label}
            onChange={(e) => onChange('label', e.target.value)}
            className="w-full px-3 py-2 text-sm border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="Enter label"
          />
        </PropertyField>
        <PropertyField label="Type">
          <input
            type="text"
            value={control.type}
            disabled
            className="w-full px-3 py-2 text-sm bg-gray-50 border border-gray-200 rounded text-gray-500"
          />
        </PropertyField>
        <PropertyField label="Width">
          <select
            value={control.width}
            onChange={(e) => onChange('width', e.target.value)}
            className="w-full px-3 py-2 text-sm border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="100%">100%</option>
            <option value="75%">75%</option>
            <option value="50%">50%</option>
            <option value="33.33%">33.33%</option>
            <option value="25%">25%</option>
          </select>
        </PropertyField>
      </PropertySection>

      {/* Permissions */}
      <PropertySection title="Permission Configuration">
        <PropertyField label="View Permission">
          <div
            onClick={() => {
              onOpenMembershipSelector({
                mode: 'multiple',
                allowedTypes: ['role', 'department'],
                title: 'Select roles/departments that can view',
                onConfirm: (selected: MembershipEntity[]) => {
                  console.log('View permission:', selected);
                },
              });
            }}
            className="w-full px-3 py-2 text-sm border border-gray-300 rounded cursor-pointer hover:border-blue-500"
          >
            <span className="text-gray-400">Everyone</span>
          </div>
        </PropertyField>
        <PropertyField label="Edit Permission">
          <div
            onClick={() => {
              onOpenMembershipSelector({
                mode: 'multiple',
                allowedTypes: ['role', 'department'],
                title: 'Select roles/departments that can edit',
                onConfirm: (selected: MembershipEntity[]) => {
                  console.log('Edit permission:', selected);
                },
              });
            }}
            className="w-full px-3 py-2 text-sm border border-gray-300 rounded cursor-pointer hover:border-blue-500"
          >
            <span className="text-gray-400">Everyone</span>
          </div>
        </PropertyField>
      </PropertySection>

      {/* Data Binding */}
      <PropertySection title="Data Binding">
        <PropertyField label="BPMN Variable">
          <input
            type="text"
            value={control.dataBinding?.bpmnVariable || ''}
            onChange={(e) => onChange('dataBinding', { ...control.dataBinding, bpmnVariable: e.target.value })}
            className="w-full px-3 py-2 text-sm border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="Enter variable name"
          />
        </PropertyField>
      </PropertySection>
    </div>
  );
};

// Binding Properties
interface BindingPropertiesProps {
  binding: TaskFormBinding;
  onChange: (property: string, value: any) => void;
}

const BindingProperties: React.FC<BindingPropertiesProps> = ({
  binding,
  onChange,
}) => {
  return (
    <div className="space-y-4">
      <PropertySection title="Binding Information">
        <PropertyField label="Task">
          <input
            type="text"
            value={binding.taskName}
            disabled
            className="w-full px-3 py-2 text-sm bg-gray-50 border border-gray-200 rounded text-gray-500"
          />
        </PropertyField>
        <PropertyField label="Form">
          <input
            type="text"
            value={binding.formName}
            disabled
            className="w-full px-3 py-2 text-sm bg-gray-50 border border-gray-200 rounded text-gray-500"
          />
        </PropertyField>
      </PropertySection>

      <PropertySection title="Permission Synchronization">
        <PropertyField label="Enable Sync">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={binding.permissionSync?.enabled || false}
              onChange={(e) => onChange('permissionSync.enabled', e.target.checked)}
              className="w-4 h-4 text-blue-600 rounded focus:ring-blue-500"
            />
            <span className="text-sm text-gray-700">Automatically sync executor permissions to form</span>
          </label>
        </PropertyField>
      </PropertySection>
    </div>
  );
};

// Property Section Component
interface PropertySectionProps {
  title: string;
  children: React.ReactNode;
  collapsible?: boolean;
}

const PropertySection: React.FC<PropertySectionProps> = ({
  title,
  children,
  collapsible = true,
}) => {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <div
        className={`px-3 py-2 bg-gray-50 flex items-center justify-between ${
          collapsible ? 'cursor-pointer' : ''
        }`}
        onClick={() => collapsible && setCollapsed(!collapsed)}
      >
        <span className="text-sm font-medium text-gray-700">{title}</span>
        {collapsible && (
          <svg
            className={`w-4 h-4 text-gray-400 transition-transform ${
              collapsed ? '' : 'rotate-180'
            }`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        )}
      </div>
      {!collapsed && (
        <div className="p-3 space-y-3">
          {children}
        </div>
      )}
    </div>
  );
};

// Property Field Component
interface PropertyFieldProps {
  label: string;
  children: React.ReactNode;
}

const PropertyField: React.FC<PropertyFieldProps> = ({ label, children }) => (
  <div>
    <label className="block text-xs font-medium text-gray-500 mb-1">{label}</label>
    {children}
  </div>
);

export default PropertiesPanel;
