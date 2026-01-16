/**
 * Form Editor Component (New - BPM FormSchema Aligned)
 *
 * Supports 37 BPM control types
 * Features:
 * - Control palette with categories
 * - Drag & drop form building
 * - Control properties editing
 * - Permission configuration
 * - BPMN variable binding
 */

import React, { useState } from 'react';
import {
  FormDefinition,
  FormControl,
  BpmnVariable,
  ControlType,
  ControlCategory,
  getControlsByCategory,
  getControlMetadata,
} from '../../types/workflow';

interface FormEditorNewProps {
  formDefinition: FormDefinition;
  onFormChange: (form: FormDefinition) => void;
  onControlSelect: (control: FormControl | null) => void;
  selectedControl: FormControl | null;
  bpmnVariables?: BpmnVariable[];
  readOnly?: boolean;
}

const FormEditorNew: React.FC<FormEditorNewProps> = ({
  formDefinition,
  onFormChange,
  onControlSelect,
  selectedControl,
  bpmnVariables: _bpmnVariables = [],
  readOnly = false,
}) => {
  const [paletteCollapsed, setPaletteCollapsed] = useState(false);
  const [activeCategory, setActiveCategory] = useState<ControlCategory>('basic');

  // Normalize form definition to use 'controls' property
  // Handle both 'controls' and 'fields' for backward compatibility
  const normalizedFormDef = {
    ...formDefinition,
    controls: formDefinition.controls || (formDefinition as any).fields || [],
  };

  // Add control to form
  const handleAddControl = (type: ControlType) => {
    if (readOnly) return;

    const metadata = getControlMetadata(type);
    if (!metadata) return;

    const newControl: FormControl = {
      id: `control-${Date.now()}`,
      type,
      label: metadata.label,
      props: { ...metadata.defaultProps },
      width: metadata.defaultWidth,
    };

    onFormChange({
      ...normalizedFormDef,
      controls: [...normalizedFormDef.controls, newControl],
    });
  };

  // Remove control
  const handleRemoveControl = (controlId: string) => {
    if (readOnly) return;

    onFormChange({
      ...normalizedFormDef,
      controls: normalizedFormDef.controls.filter(c => c.id !== controlId),
    });

    if (selectedControl?.id === controlId) {
      onControlSelect(null);
    }
  };

  // Move control
  const handleMoveControl = (controlId: string, direction: 'up' | 'down') => {
    if (readOnly) return;

    const index = normalizedFormDef.controls.findIndex(c => c.id === controlId);
    if (index === -1) return;

    const newIndex = direction === 'up' ? index - 1 : index + 1;
    if (newIndex < 0 || newIndex >= normalizedFormDef.controls.length) return;

    const newControls = [...normalizedFormDef.controls];
    [newControls[index], newControls[newIndex]] = [newControls[newIndex], newControls[index]];

    onFormChange({
      ...normalizedFormDef,
      controls: newControls,
    });
  };

  // Update form title
  const handleTitleChange = (title: string) => {
    onFormChange({
      ...normalizedFormDef,
      title,
    });
  };

  // Category labels
  const categoryLabels: Record<ControlCategory, string> = {
    basic: 'Basic Input',
    selection: 'Selection',
    datetime: 'Date & Time',
    advanced: 'Advanced',
    file: 'File & Media',
    layout: 'Layout',
    special: 'Special',
    business: 'Business',
  };

  const categories: ControlCategory[] = [
    'basic', 'selection', 'datetime', 'advanced', 'file', 'layout', 'special', 'business'
  ];

  return (
    <div className="h-full flex bg-gray-50">
      {/* Control Palette */}
      <div
        className={`bg-white border-r border-gray-200 flex flex-col transition-all duration-300 ${
          paletteCollapsed ? 'w-12' : 'w-64'
        }`}
      >
        {/* Palette Header */}
        <div className="p-3 border-b border-gray-200 flex items-center justify-between">
          {!paletteCollapsed && (
            <span className="font-medium text-gray-800 text-sm">Controls</span>
          )}
          <button
            onClick={() => setPaletteCollapsed(!paletteCollapsed)}
            className="p-1 text-gray-400 hover:text-gray-600 rounded"
          >
            <svg
              className={`w-5 h-5 transition-transform ${paletteCollapsed ? 'rotate-180' : ''}`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
            </svg>
          </button>
        </div>

        {/* Palette Content */}
        {!paletteCollapsed && (
          <div className="flex-1 overflow-y-auto">
            {/* Category Tabs */}
            <div className="p-2 border-b border-gray-200">
              <div className="flex flex-wrap gap-1">
                {categories.map(cat => (
                  <button
                    key={cat}
                    onClick={() => setActiveCategory(cat)}
                    className={`px-2 py-1 text-xs rounded transition-colors ${
                      activeCategory === cat
                        ? 'bg-blue-100 text-blue-700'
                        : 'text-gray-600 hover:bg-gray-100'
                    }`}
                  >
                    {categoryLabels[cat]}
                  </button>
                ))}
              </div>
            </div>

            {/* Controls List */}
            <div className="p-2 space-y-1">
              {getControlsByCategory(activeCategory).map(control => (
                <button
                  key={control.type}
                  onClick={() => handleAddControl(control.type)}
                  disabled={readOnly}
                  className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100 rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <ControlIcon type={control.type} />
                  <span>{control.label}</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Form Canvas */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Form Header */}
        <div className="p-4 bg-white border-b border-gray-200">
          <input
            type="text"
            value={normalizedFormDef.title}
            onChange={(e) => handleTitleChange(e.target.value)}
            className="text-xl font-semibold text-gray-800 bg-transparent border-none outline-none focus:ring-0 w-full"
            placeholder="Form Title"
            disabled={readOnly}
          />
          {normalizedFormDef.description && (
            <p className="text-sm text-gray-500 mt-1">{normalizedFormDef.description}</p>
          )}
        </div>

        {/* Canvas Area */}
        <div className="flex-1 overflow-y-auto p-4">
          {normalizedFormDef.controls.length === 0 ? (
            <div className="h-full flex items-center justify-center">
              <div className="text-center text-gray-500">
                <svg className="w-16 h-16 mx-auto mb-4 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                <p className="text-lg mb-1">Start Designing Your Form</p>
                <p className="text-sm">Select controls from the left panel to add to your form</p>
              </div>
            </div>
          ) : (
            <div className="max-w-3xl mx-auto space-y-3">
              {normalizedFormDef.controls.map((control, index) => (
                <ControlItem
                  key={control.id}
                  control={control}
                  selected={selectedControl?.id === control.id}
                  onSelect={() => onControlSelect(control)}
                  onRemove={() => handleRemoveControl(control.id)}
                  onMoveUp={() => handleMoveControl(control.id, 'up')}
                  onMoveDown={() => handleMoveControl(control.id, 'down')}
                  isFirst={index === 0}
                  isLast={index === normalizedFormDef.controls.length - 1}
                  readOnly={readOnly}
                />
              ))}
            </div>
          )}
        </div>

        {/* Canvas Footer */}
        <div className="p-3 bg-white border-t border-gray-200 text-sm text-gray-500 flex items-center justify-between">
          <span>{normalizedFormDef.controls.length} controls</span>
          <span>Form Type: {normalizedFormDef.formType}</span>
        </div>
      </div>
    </div>
  );
};

// Control Item Component
interface ControlItemProps {
  control: FormControl;
  selected: boolean;
  onSelect: () => void;
  onRemove: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
  isFirst: boolean;
  isLast: boolean;
  readOnly: boolean;
}

const ControlItem: React.FC<ControlItemProps> = ({
  control,
  selected,
  onSelect,
  onRemove,
  onMoveUp,
  onMoveDown,
  isFirst,
  isLast,
  readOnly,
}) => {
  return (
    <div
      onClick={onSelect}
      style={{ width: control.width }}
      className={`group relative bg-white rounded-lg border p-4 cursor-pointer transition-all ${
        selected
          ? 'border-blue-500 ring-2 ring-blue-100'
          : 'border-gray-200 hover:border-gray-300'
      }`}
    >
      {/* Control Label */}
      <div className="flex items-center gap-2 mb-2">
        <ControlIcon type={control.type} className="w-4 h-4 text-gray-400" />
        <label className="text-sm font-medium text-gray-700">
          {control.label}
          {control.permissions?.required?.condition === 'true' && (
            <span className="text-red-500 ml-1">*</span>
          )}
        </label>
      </div>

      {/* Control Preview */}
      <ControlPreview control={control} />

      {/* Action Buttons */}
      {!readOnly && (
        <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity flex gap-1">
          {!isFirst && (
            <button
              onClick={(e) => { e.stopPropagation(); onMoveUp(); }}
              className="p-1 text-gray-400 hover:text-gray-600 bg-white rounded shadow-sm"
              title="Move Up"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" />
              </svg>
            </button>
          )}
          {!isLast && (
            <button
              onClick={(e) => { e.stopPropagation(); onMoveDown(); }}
              className="p-1 text-gray-400 hover:text-gray-600 bg-white rounded shadow-sm"
              title="Move Down"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>
          )}
          <button
            onClick={(e) => { e.stopPropagation(); onRemove(); }}
            className="p-1 text-gray-400 hover:text-red-500 bg-white rounded shadow-sm"
            title="Delete"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
            </svg>
          </button>
        </div>
      )}

      {/* Type Badge */}
      <div className="absolute bottom-2 right-2 px-2 py-0.5 bg-gray-100 text-gray-500 text-xs rounded">
        {control.type}
      </div>
    </div>
  );
};

// Control Preview Component
interface ControlPreviewProps {
  control: FormControl;
}

const ControlPreview: React.FC<ControlPreviewProps> = ({ control }) => {
  const { type, props } = control;

  switch (type) {
    case 'text':
    case 'email':
    case 'phone':
    case 'url':
    case 'password':
      return (
        <input
          type="text"
          placeholder={props?.placeholder || 'Enter value...'}
          className="w-full px-3 py-2 text-sm border border-gray-300 rounded bg-gray-50 cursor-pointer"
          disabled
        />
      );

    case 'textarea':
      return (
        <textarea
          placeholder={props?.placeholder || 'Enter value...'}
          rows={props?.rows || 3}
          className="w-full px-3 py-2 text-sm border border-gray-300 rounded bg-gray-50 cursor-pointer resize-none"
          disabled
        />
      );

    case 'number':
      return (
        <input
          type="number"
          placeholder="0"
          className="w-full px-3 py-2 text-sm border border-gray-300 rounded bg-gray-50 cursor-pointer"
          disabled
        />
      );

    case 'select':
      return (
        <select className="w-full px-3 py-2 text-sm border border-gray-300 rounded bg-gray-50 cursor-pointer" disabled>
          <option>Select an option...</option>
        </select>
      );

    case 'multiselect':
      return (
        <div className="w-full px-3 py-2 text-sm border border-gray-300 rounded bg-gray-50 text-gray-400">
          Select multiple options...
        </div>
      );

    case 'radio':
      return (
        <div className="flex gap-4">
          {(props?.options || [{ label: 'Option 1' }, { label: 'Option 2' }]).slice(0, 3).map((opt: any, i: number) => (
            <label key={i} className="flex items-center gap-2 text-sm text-gray-600">
              <input type="radio" disabled className="cursor-pointer" />
              {opt.label}
            </label>
          ))}
        </div>
      );

    case 'checkbox':
      return (
        <div className="flex gap-4">
          {(props?.options || [{ label: 'Option 1' }, { label: 'Option 2' }]).slice(0, 3).map((opt: any, i: number) => (
            <label key={i} className="flex items-center gap-2 text-sm text-gray-600">
              <input type="checkbox" disabled className="cursor-pointer" />
              {opt.label}
            </label>
          ))}
        </div>
      );

    case 'date':
    case 'datetime':
      return (
        <input
          type="text"
          placeholder={type === 'date' ? 'Select date' : 'Select date & time'}
          className="w-full px-3 py-2 text-sm border border-gray-300 rounded bg-gray-50 cursor-pointer"
          disabled
        />
      );

    case 'daterange':
      return (
        <div className="flex items-center gap-2">
          <input type="text" placeholder="Start Date" className="flex-1 px-3 py-2 text-sm border border-gray-300 rounded bg-gray-50" disabled />
          <span className="text-gray-400">~</span>
          <input type="text" placeholder="End Date" className="flex-1 px-3 py-2 text-sm border border-gray-300 rounded bg-gray-50" disabled />
        </div>
      );

    case 'upload':
    case 'image':
      return (
        <div className="w-full p-4 border-2 border-dashed border-gray-300 rounded text-center text-gray-400 text-sm">
          Click or drag to upload {type === 'image' ? 'image' : 'file'}
        </div>
      );

    case 'richtext':
      return (
        <div className="w-full h-24 border border-gray-300 rounded bg-gray-50 p-2 text-gray-400 text-sm">
          Rich Text Editor
        </div>
      );

    case 'signature':
      return (
        <div className="w-full h-20 border border-gray-300 rounded bg-gray-50 flex items-center justify-center text-gray-400 text-sm">
          Signature Area
        </div>
      );

    case 'section':
      return (
        <div className="w-full p-3 bg-gray-100 rounded text-gray-600 text-sm font-medium">
          {props?.title || 'Section Title'}
        </div>
      );

    case 'divider':
      return <hr className="border-gray-300" />;

    case 'user_selector':
    case 'department_selector':
      return (
        <div className="w-full px-3 py-2 text-sm border border-gray-300 rounded bg-gray-50 text-gray-400 flex items-center justify-between">
          <span>Click to select {type === 'user_selector' ? 'user' : 'department'}...</span>
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 9l4-4 4 4m0 6l-4 4-4-4" />
          </svg>
        </div>
      );

    default:
      return (
        <div className="w-full px-3 py-2 text-sm border border-gray-300 rounded bg-gray-50 text-gray-400">
          {type} control preview
        </div>
      );
  }
};

// Control Icon Component
interface ControlIconProps {
  type: ControlType;
  className?: string;
}

const ControlIcon: React.FC<ControlIconProps> = ({ type, className = 'w-5 h-5' }) => {
  // Simple icon mapping - in production, use a proper icon library
  const iconPaths: Record<string, string> = {
    text: 'M4 6h16M4 12h16M4 18h7',
    textarea: 'M4 6h16M4 10h16M4 14h16M4 18h10',
    number: 'M7 20l4-16m2 16l4-16M6 9h14M4 15h14',
    email: 'M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z',
    phone: 'M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z',
    select: 'M19 9l-7 7-7-7',
    checkbox: 'M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z',
    radio: 'M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z',
    date: 'M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z',
    upload: 'M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12',
    user_selector: 'M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z',
    department_selector: 'M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4',
  };

  const path = iconPaths[type] || 'M4 6h16M4 12h16M4 18h16';

  return (
    <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={path} />
    </svg>
  );
};

export default FormEditorNew;
