import React from 'react';
import { ValidationResult } from '../../types/bpmn';

interface ValidationPanelProps {
  validation: ValidationResult | null;
}

const ValidationPanel: React.FC<ValidationPanelProps> = ({ validation }) => {
  if (!validation) {
    return null;
  }

  const { valid, errors, warnings } = validation;

  return (
    <div className={`p-4 border-t ${valid ? 'bg-green-50' : 'bg-red-50'}`}>
      <h4 className="font-semibold mb-2">
        {valid ? '✓ Valid BPMN' : '✗ Validation Errors'}
      </h4>

      {errors.length > 0 && (
        <div className="mb-3">
          <p className="text-sm font-medium text-red-800 mb-1">Errors:</p>
          <ul className="text-sm text-red-700 space-y-1">
            {errors.map((error, i) => (
              <li key={i}>• {error}</li>
            ))}
          </ul>
        </div>
      )}

      {warnings.length > 0 && (
        <div>
          <p className="text-sm font-medium text-yellow-800 mb-1">Warnings:</p>
          <ul className="text-sm text-yellow-700 space-y-1">
            {warnings.map((warning, i) => (
              <li key={i}>• {warning}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};

export default ValidationPanel;
