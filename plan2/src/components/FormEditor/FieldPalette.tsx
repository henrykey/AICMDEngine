import React from 'react';

interface FieldPaletteProps {
  onAddField: (fieldType: string) => void;
}

const FIELD_TYPES = [
  { id: 'text', label: 'Text', icon: '📝' },
  { id: 'number', label: 'Number', icon: '🔢' },
  { id: 'date', label: 'Date', icon: '📅' },
  { id: 'select', label: 'Select', icon: '⬇️' },
  { id: 'checkbox', label: 'Checkbox', icon: '☑️' },
  { id: 'file', label: 'File', icon: '📎' },
];

const FieldPalette: React.FC<FieldPaletteProps> = ({ onAddField }) => {
  return (
    <div className="w-48 bg-white rounded-lg border border-gray-300 p-4">
      <h3 className="font-semibold text-sm mb-4">Field Types</h3>
      <div className="space-y-2">
        {FIELD_TYPES.map((field) => (
          <button
            key={field.id}
            onClick={() => onAddField(field.id)}
            className="w-full flex items-center gap-2 p-2 bg-blue-50 hover:bg-blue-100 rounded border border-blue-200 text-sm font-medium text-blue-900 transition"
          >
            <span>{field.icon}</span>
            <span>{field.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
};

export default FieldPalette;
