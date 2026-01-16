/**
 * Workflow Designer Page
 *
 * Main page for designing workflows with:
 * - BPMN Process Editor
 * - Form Editor (BPM FormSchema)
 * - Bindings View
 * - AI Chat Panel
 * - Properties Panel (slide-out)
 */

import React, { useState, useCallback } from 'react';
import {
  Workflow,
  FormDefinition,
  BpmnElement,
  FormControl,
  TaskFormBinding,
  ChatMessage,
  ValidationResult,
} from '../types/workflow';
import ProcessEditor from '../components/ProcessEditor/ProcessEditor';
import FormEditorNew from '../components/FormEditor/FormEditorNew';
import BindingsView from '../components/BindingsView/BindingsView';
import ChatPanel from '../components/ChatPanel/ChatPanel';
import PropertiesPanel from '../components/PropertiesPanel/PropertiesPanel';
import ValidationBar from '../components/ValidationBar/ValidationBar';

// Tab types
type TabType = 'process' | 'form' | 'bindings';

// Default empty form
const createEmptyForm = (): FormDefinition => ({
  formId: `form-${Date.now()}`,
  version: '1.0.0',
  title: 'New Form',
  description: '',
  controls: [],
  formType: 'standalone',
  layout: {
    columns: 1,
    labelPosition: 'top',
  },
});

// Default empty BPMN
const DEFAULT_BPMN = `<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
                  xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"
                  id="Definitions_1">
  <bpmn:process id="Process_1" name="New Process" isExecutable="true">
    <bpmn:startEvent id="StartEvent_1" name="Start"/>
    <bpmn:endEvent id="EndEvent_1" name="End"/>
  </bpmn:process>
</bpmn:definitions>`;

const WorkflowDesigner: React.FC = () => {
  // === State ===

  // Active tab
  const [activeTab, setActiveTab] = useState<TabType>('process');

  // BPMN state
  const [bpmnXml, setBpmnXml] = useState<string>(DEFAULT_BPMN);
  const [selectedBpmnElement, setSelectedBpmnElement] = useState<BpmnElement | null>(null);

  // Form state
  const [formDefinition, setFormDefinition] = useState<FormDefinition>(createEmptyForm());
  const [selectedControl, setSelectedControl] = useState<FormControl | null>(null);

  // Bindings state
  const [bindings, setBindings] = useState<TaskFormBinding[]>([]);
  const [selectedBinding, setSelectedBinding] = useState<TaskFormBinding | null>(null);

  // UI state
  const [propertiesPanelOpen, setPropertiesPanelOpen] = useState(false);
  const [chatPanelCollapsed, setChatPanelCollapsed] = useState(false);
  const [chatPanelWidth, setChatPanelWidth] = useState(320); // 80 * 4 = 320px
  const [isDraggingDivider, setIsDraggingDivider] = useState(false);

  // Validation state
  const [processValidation, _setProcessValidation] = useState<ValidationResult | null>(null);
  const [formValidation, _setFormValidation] = useState<ValidationResult | null>(null);

  // Chat state
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);

  // Saving state
  const [saving, setSaving] = useState(false);
  const [workflowName, setWorkflowName] = useState('New Workflow');

  // === Handlers ===

  // Tab change
  const handleTabChange = useCallback((tab: TabType) => {
    setActiveTab(tab);
    // Clear selection when switching tabs
    if (tab !== 'process') setSelectedBpmnElement(null);
    if (tab !== 'form') setSelectedControl(null);
    if (tab !== 'bindings') setSelectedBinding(null);
  }, []);

  // BPMN handlers
  const handleBpmnChange = useCallback((xml: string) => {
    setBpmnXml(xml);
  }, []);

  const handleBpmnElementSelect = useCallback((element: BpmnElement | null) => {
    setSelectedBpmnElement(element);
    if (element) {
      setPropertiesPanelOpen(true);
    }
  }, []);

  // Form handlers
  const handleFormChange = useCallback((form: FormDefinition) => {
    setFormDefinition(form);
  }, []);

  const handleControlSelect = useCallback((control: FormControl | null) => {
    setSelectedControl(control);
    if (control) {
      setPropertiesPanelOpen(true);
    }
  }, []);

  // Binding handlers
  const handleBindingSelect = useCallback((binding: TaskFormBinding | null) => {
    setSelectedBinding(binding);
    if (binding) {
      setPropertiesPanelOpen(true);
    }
  }, []);

  // Properties panel
  const handlePropertiesClose = useCallback(() => {
    setPropertiesPanelOpen(false);
  }, []);

  const handlePropertyChange = useCallback((property: string, value: any) => {
    if (activeTab === 'process' && selectedBpmnElement) {
      // Handle BPMN property change
      console.log('BPMN property change:', property, value);
    } else if (activeTab === 'form' && selectedControl) {
      // Handle Form control property change
      const updatedControls = formDefinition.controls.map(c =>
        c.id === selectedControl.id ? { ...c, [property]: value } : c
      );
      setFormDefinition({ ...formDefinition, controls: updatedControls });
    }
  }, [activeTab, selectedBpmnElement, selectedControl, formDefinition]);

  // Chat handlers
  const handleApplyToProcess = useCallback((generatedBpmn: string) => {
    setBpmnXml(generatedBpmn);
    setActiveTab('process');
  }, []);

  const handleApplyToForm = useCallback((generatedForm: FormDefinition) => {
    setFormDefinition(generatedForm);
    setActiveTab('form');
  }, []);

  // Save handler
  const handleSave = useCallback(async () => {
    setSaving(true);
    try {
      const workflow: Partial<Workflow> = {
        name: workflowName,
        version: '1.0.0',
        status: 'draft',
        process: {
          bpmnXml,
          processId: 'Process_1',
          processName: workflowName,
        },
        forms: [formDefinition],
        bindings,
      };

      const response = await fetch('/api/v1/workflows', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(workflow),
      });

      if (response.ok) {
        alert('Workflow saved successfully!');
      } else {
        alert('Save failed, please try again');
      }
    } catch (err) {
      console.error('Save error:', err);
      alert(`Save error: ${err}`);
    } finally {
      setSaving(false);
    }
  }, [workflowName, bpmnXml, formDefinition, bindings]);

  // Get current validation based on active tab
  const currentValidation = activeTab === 'process' ? processValidation : formValidation;

  // Get selected element for properties panel
  const getSelectedElement = () => {
    switch (activeTab) {
      case 'process': return selectedBpmnElement;
      case 'form': return selectedControl;
      case 'bindings': return selectedBinding;
      default: return null;
    }
  };

  // Handle divider drag
  const handleDividerMouseDown = useCallback(() => {
    setIsDraggingDivider(true);
  }, []);

  React.useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isDraggingDivider) return;

      // Get the viewport width
      const viewportWidth = window.innerWidth;
      // Calculate new width based on mouse position
      // Subtract header/footer height and ensure minimum/maximum bounds
      const newWidth = viewportWidth - e.clientX;

      // Constrain width between 200px and 600px
      if (newWidth >= 200 && newWidth <= 600) {
        setChatPanelWidth(newWidth);
      }
    };

    const handleMouseUp = () => {
      setIsDraggingDivider(false);
    };

    if (isDraggingDivider) {
      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
    }

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDraggingDivider]);

  return (
    <div className="h-screen flex flex-col bg-gray-100">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 px-4 py-3 flex items-center justify-between shadow-sm">
        <div className="flex items-center gap-4">
          <h1 className="text-xl font-semibold text-gray-800">Workflow Designer</h1>
          <input
            type="text"
            value={workflowName}
            onChange={(e) => setWorkflowName(e.target.value)}
            className="px-3 py-1.5 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="Workflow name"
          />
        </div>
        <div className="flex items-center gap-3">
          <button
            className="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-800 hover:bg-gray-100 rounded-md transition-colors"
          >
            Preview
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-1.5 text-sm bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:bg-gray-400 transition-colors"
          >
            {saving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </header>

      {/* Tab Bar */}
      <div className="bg-white border-b border-gray-200 px-4 flex items-center justify-between h-14">
        <div className="flex">
          <TabButton
            active={activeTab === 'process'}
            onClick={() => handleTabChange('process')}
          >
            Process Design
          </TabButton>
          <TabButton
            active={activeTab === 'form'}
            onClick={() => handleTabChange('form')}
          >
            Form Design
          </TabButton>
          <TabButton
            active={activeTab === 'bindings'}
            onClick={() => handleTabChange('bindings')}
          >
            Bindings
          </TabButton>
        </div>
        <button
          onClick={() => setPropertiesPanelOpen(!propertiesPanelOpen)}
          className={`p-2 rounded-md transition-colors ${
            propertiesPanelOpen
              ? 'bg-blue-100 text-blue-600'
              : 'text-gray-500 hover:bg-gray-100'
          }`}
          title="Properties Panel"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
        </button>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Canvas Area */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Editor Canvas */}
          <div className="flex-1 overflow-hidden">
            {activeTab === 'process' && (
              <ProcessEditor
                bpmnXml={bpmnXml}
                onBpmnChange={handleBpmnChange}
                onElementSelect={handleBpmnElementSelect}
                selectedElement={selectedBpmnElement}
                validationMode="design"
              />
            )}
            {activeTab === 'form' && (
              <FormEditorNew
                formDefinition={formDefinition}
                onFormChange={handleFormChange}
                onControlSelect={handleControlSelect}
                selectedControl={selectedControl}
                bpmnVariables={[]}
              />
            )}
            {activeTab === 'bindings' && (
              <BindingsView
                bindings={bindings}
                bpmnXml={bpmnXml}
                forms={[formDefinition]}
                onBindingSelect={handleBindingSelect}
                selectedBinding={selectedBinding}
                onBindingsChange={setBindings}
              />
            )}
          </div>

          {/* Validation Bar */}
          <ValidationBar validation={currentValidation} />
        </div>

        {/* Draggable Divider */}
        {!chatPanelCollapsed && (
          <div
            className="w-1 bg-gray-300 hover:bg-blue-500 cursor-col-resize transition-colors"
            onMouseDown={handleDividerMouseDown}
            title="Drag to resize chat panel"
          />
        )}

        {/* Chat Panel */}
        <div
          className={`border-l border-gray-200 bg-white transition-all duration-300 overflow-hidden ${
            chatPanelCollapsed ? 'w-12' : ''
          }`}
          style={{ width: chatPanelCollapsed ? 'auto' : `${chatPanelWidth}px` }}
        >
          <ChatPanel
            collapsed={chatPanelCollapsed}
            onToggleCollapse={() => setChatPanelCollapsed(!chatPanelCollapsed)}
            messages={chatMessages}
            onMessagesChange={setChatMessages}
            onApplyToProcess={handleApplyToProcess}
            onApplyToForm={handleApplyToForm}
            currentContext={{
              bpmnXml,
              formDefinition,
              selectedElement: selectedBpmnElement || undefined,
            }}
          />
        </div>

        {/* Properties Panel (Slide-out) */}
        <PropertiesPanel
          open={propertiesPanelOpen}
          onClose={handlePropertiesClose}
          activeTab={activeTab}
          selectedElement={getSelectedElement()}
          onPropertyChange={handlePropertyChange}
          bpmnXml={bpmnXml}
          formDefinition={formDefinition}
        />
      </div>
    </div>
  );
};

// Tab Button Component
interface TabButtonProps {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}

const TabButton: React.FC<TabButtonProps> = ({ active, onClick, children }) => (
  <button
    onClick={onClick}
    className={`px-4 h-14 flex items-center justify-center text-sm font-medium border-b-2 transition-colors whitespace-nowrap ${
      active
        ? 'border-blue-600 text-blue-600'
        : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
    }`}
  >
    {children}
  </button>
);

export default WorkflowDesigner;
