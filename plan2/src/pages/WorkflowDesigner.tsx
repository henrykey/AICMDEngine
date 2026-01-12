import React, { useState } from 'react';
import ProcessEditor from '../components/ProcessEditor/ProcessEditor';
import FormEditor from '../components/FormEditor/FormEditor';
import { FormDefinition } from '../types/bpmn';

const WorkflowDesigner: React.FC = () => {
  const [bpmnXml, setBpmnXml] = useState<string>('');
  const [form, setForm] = useState<FormDefinition>({
    id: '',
    name: '',
    fields: [],
  });
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      const response = await fetch('/api/v1/workflows', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ bpmn_xml: bpmnXml, form }),
      });

      if (response.ok) {
        alert('Workflow saved successfully!');
      } else {
        alert('Failed to save workflow');
      }
    } catch (err) {
      alert(`Error: ${err}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="w-full h-screen flex flex-col">
      {/* Header */}
      <div className="bg-white border-b border-gray-300 p-4 flex items-center justify-between">
        <h1 className="text-2xl font-bold">Workflow Designer</h1>
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:bg-gray-400"
        >
          {saving ? 'Saving...' : 'Save Workflow'}
        </button>
      </div>

      {/* Main Layout */}
      <div className="flex-1 flex gap-4 p-4 overflow-hidden">
        {/* Left: Process Editor */}
        <div className="flex-1 flex flex-col">
          <h2 className="text-lg font-semibold mb-2">BPMN Process</h2>
          <div className="flex-1 bg-white rounded-lg border border-gray-300 overflow-hidden">
            <ProcessEditor
              bpmnXml={bpmnXml}
              onBpmnChange={setBpmnXml}
            />
          </div>
        </div>

        {/* Right: Form Editor */}
        <div className="flex-1 flex flex-col">
          <h2 className="text-lg font-semibold mb-2">Process Form</h2>
          <div className="flex-1 bg-white rounded-lg border border-gray-300 overflow-hidden">
            <FormEditor
              formJson={form}
              onFormChange={setForm}
              bpmnXml={bpmnXml}
            />
          </div>
        </div>
      </div>
    </div>
  );
};

export default WorkflowDesigner;
