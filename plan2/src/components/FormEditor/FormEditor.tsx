import React, { useState } from 'react';
import { FormDefinition, FormEditorProps } from '../../types/bpmn';
import FieldPalette from './FieldPalette';
import FormCanvas from './FormCanvas';

const FormEditor: React.FC<FormEditorProps> = ({
  formJson = { id: '', name: '', fields: [] },
  onFormChange,
  readOnly = false,
}) => {
  const [selectedFieldId, setSelectedFieldId] = useState<string | null>(null);

  const handleAddField = (fieldType: string) => {
    const newField = {
      id: `field_${Date.now()}`,
      name: `${fieldType}_${formJson.fields.length + 1}`,
      type: fieldType as any,
      label: fieldType.charAt(0).toUpperCase() + fieldType.slice(1),
      required: false,
    };

    const updatedForm: FormDefinition = {
      ...formJson,
      fields: [...formJson.fields, newField],
    };

    onFormChange(updatedForm);
  };

  const handleRemoveField = (fieldId: string) => {
    const updatedForm: FormDefinition = {
      ...formJson,
      fields: formJson.fields.filter((f) => f.id !== fieldId),
    };

    onFormChange(updatedForm);
    setSelectedFieldId(null);
  };

  const handleUpdateField = (fieldId: string, updates: any) => {
    const updatedForm: FormDefinition = {
      ...formJson,
      fields: formJson.fields.map((f) =>
        f.id === fieldId ? { ...f, ...updates } : f
      ),
    };

    onFormChange(updatedForm);
  };

  return (
    <div className="w-full h-full flex gap-4 p-4 bg-gray-50">
      {/* Field Palette */}
      <FieldPalette onAddField={handleAddField} />

      {/* Canvas */}
      <div className="flex-1 flex flex-col">
        <div className="mb-3">
          <input
            type="text"
            value={formJson.name}
            onChange={(e) =>
              onFormChange({ ...formJson, name: e.target.value })
            }
            placeholder="Form Name"
            className="text-xl font-semibold px-3 py-2 border border-gray-300 rounded"
            disabled={readOnly}
          />
        </div>

        <FormCanvas
          form={formJson}
          selectedFieldId={selectedFieldId}
          onSelectField={setSelectedFieldId}
          onRemoveField={handleRemoveField}
          onUpdateField={handleUpdateField}
          readOnly={readOnly}
        />
      </div>
    </div>
  );
};

export default FormEditor;
