/**
 * Validation Bar Component
 *
 * Displays validation status at the bottom of the canvas
 */

import React, { useState } from 'react';
import { ValidationResult, ValidationMessage } from '../../types/workflow';

interface ValidationBarProps {
  validation: ValidationResult | null;
}

const ValidationBar: React.FC<ValidationBarProps> = ({ validation }) => {
  const [expanded, setExpanded] = useState(false);

  if (!validation) {
    return (
      <div className="h-10 bg-white border-t border-gray-200 px-4 flex items-center text-sm text-gray-500">
        <span>Awaiting validation...</span>
      </div>
    );
  }

  const { valid, errors, warnings } = validation;
  const hasIssues = errors.length > 0 || warnings.length > 0;

  return (
    <div className="bg-white border-t border-gray-200">
      {/* Summary Bar */}
      <div
        className={`h-10 px-4 flex items-center justify-between cursor-pointer hover:bg-gray-50 ${
          hasIssues ? '' : ''
        }`}
        onClick={() => hasIssues && setExpanded(!expanded)}
      >
        <div className="flex items-center gap-3">
          {/* Status Icon */}
          {valid ? (
            <div className="flex items-center gap-2 text-green-600">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <span className="text-sm font-medium">Validation Passed</span>
            </div>
          ) : (
            <div className="flex items-center gap-2 text-red-600">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <span className="text-sm font-medium">Issues Found</span>
            </div>
          )}

          {/* Counts */}
          {errors.length > 0 && (
            <span className="px-2 py-0.5 text-xs font-medium bg-red-100 text-red-700 rounded-full">
              {errors.length} Error{errors.length !== 1 ? 's' : ''}
            </span>
          )}
          {warnings.length > 0 && (
            <span className="px-2 py-0.5 text-xs font-medium bg-yellow-100 text-yellow-700 rounded-full">
              {warnings.length} Warning{warnings.length !== 1 ? 's' : ''}
            </span>
          )}
        </div>

        {/* Expand Toggle */}
        {hasIssues && (
          <svg
            className={`w-4 h-4 text-gray-400 transition-transform ${expanded ? 'rotate-180' : ''}`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        )}
      </div>

      {/* Expanded Details */}
      {expanded && hasIssues && (
        <div className="border-t border-gray-200 max-h-48 overflow-y-auto">
          {errors.map((error, index) => (
            <ValidationItem key={`error-${index}`} message={error} type="error" />
          ))}
          {warnings.map((warning, index) => (
            <ValidationItem key={`warning-${index}`} message={warning} type="warning" />
          ))}
        </div>
      )}
    </div>
  );
};

// Validation Item Component
interface ValidationItemProps {
  message: ValidationMessage;
  type: 'error' | 'warning';
}

const ValidationItem: React.FC<ValidationItemProps> = ({ message, type }) => {
  const isError = type === 'error';

  return (
    <div
      className={`px-4 py-2 flex items-start gap-2 text-sm hover:bg-gray-50 cursor-pointer ${
        isError ? 'text-red-700' : 'text-yellow-700'
      }`}
    >
      {isError ? (
        <svg className="w-4 h-4 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      ) : (
        <svg className="w-4 h-4 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
        </svg>
      )}
      <div className="flex-1">
        <p>{message.message}</p>
        {message.elementId && (
          <p className="text-xs opacity-70 mt-0.5">
            Element: {message.elementId}
          </p>
        )}
      </div>
    </div>
  );
};

export default ValidationBar;
