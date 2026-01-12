import React from 'react';
import { FormDefinition, FormField } from '../../types/bpmn';

interface FormCanvasProps {
  form: FormDefinition;
  selectedFieldId: string | null;
  onSelectField: (fieldId: string) => void;
  onRemoveField: (fieldId: string) => void;
  onUpdateField: (fieldId: string, updates: any) => void;
  readOnly?: boolean;
}

const FormCanvas: React.FC<FormCanvasProps> = ({
  form,
  selectedFieldId,
  onSelectField,
  onRemoveField,
  onUpdateField,
  readOnly = false,
}) => {
  return (
    <div
      data-testid="form-canvas"
      className="flex-1 bg-white rounded-lg border border-gray-300 p-6 overflow-y-auto"
    >
      {form.fields.length === 0 ? (
        <p className="text-gray-400 text-center py-8">
          Add fields from the palette to start building your form
        </p>
      ) : (
        <div className="space-y-4 max-w-2xl">
          {form.fields.map((field) => (
            <FieldRenderer
              key={field.id}
              field={field}
              selected={selectedFieldId === field.id}
              onSelect={() => onSelectField(field.id)}
              onRemove={() => onRemoveField(field.id)}
              onUpdate={(updates) => onUpdateField(field.id, updates)}
              readOnly={readOnly}
            />
          ))}
        </div>
      )}
    </div>
  );
};

interface FieldRendererProps {
  field: FormField;
  selected: boolean;
  onSelect: () => void;
  onRemove: () => void;
  onUpdate: (updates: any) => void;
  readOnly?: boolean;
}

const FieldRenderer: React.FC<FieldRendererProps> = ({
  field,
  selected,
  onSelect,
  onRemove,
  onUpdate,
  readOnly,
}) => {
  return (
    <div
      onClick={onSelect}
      className={`p-4 rounded border-2 cursor-pointer transition ${
        selected
          ? 'border-blue-500 bg-blue-50'
          : 'border-gray-300 bg-white hover:border-gray-400'
      }`}
    >
      <div className="flex items-center justify-between mb-2">
        <input
          type="text"
          value={field.label}
          onChange={(e) => onUpdate({ label: e.target.value })}
          className="font-medium px-2 py-1 border border-gray-200 rounded flex-1"
          onClick={(e) => e.stopPropagation()}
          disabled={readOnly}
        />
        {selected && !readOnly && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onRemove();
            }}
            className="ml-2 px-2 py-1 text-red-600 hover:bg-red-100 rounded"
          >
            ✕
          </button>
        )}
      </div>

      <div className="flex items-center gap-2">
        <label className="flex items-center gap-1 text-sm">
          <input
            type="checkbox"
            checked={field.required}
            onChange={(e) => onUpdate({ required: e.target.checked })}
            disabled={readOnly}
          />
          Required
        </label>
        <span className="text-xs text-gray-500 ml-auto">{field.type}</span>
      </div>
    </div>
  );
};

export default FormCanvas;
