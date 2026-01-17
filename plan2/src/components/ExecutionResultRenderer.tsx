import React from 'react';

interface ExecutionResultRendererProps {
  data: any;
  resultContent?: string;
}

/**
 * Renders execution results in a human-readable format.
 * - Lists/arrays: rendered as tables or formatted lists
 * - Objects: rendered as key-value pairs
 * - Primitives: rendered as text
 */
const ExecutionResultRenderer: React.FC<ExecutionResultRendererProps> = ({ data, resultContent }) => {
  if (!data && !resultContent) {
    return null;
  }

  // If we have result_content (human-readable summary), show that first
  if (resultContent) {
    return (
      <div className="text-xs text-green-700 whitespace-pre-wrap leading-relaxed">
        {resultContent}
      </div>
    );
  }

  // Handle arrays (list of items)
  if (Array.isArray(data)) {
    return <ArrayRenderer items={data} />;
  }

  // Handle objects with 'data' field containing array (common API response pattern)
  if (data && typeof data === 'object' && Array.isArray(data.data)) {
    return <ArrayRenderer items={data.data} />;
  }

  // Handle objects with 'members' field (Membership API response)
  if (data && typeof data === 'object' && Array.isArray(data.members)) {
    return <ArrayRenderer items={data.members} />;
  }

  // Handle objects with 'roles' field
  if (data && typeof data === 'object' && Array.isArray(data.roles)) {
    return <ArrayRenderer items={data.roles} />;
  }

  // Handle simple objects
  if (typeof data === 'object') {
    return <ObjectRenderer obj={data} />;
  }

  // Handle primitives
  return (
    <div className="text-xs text-green-700 whitespace-pre-wrap">
      {String(data)}
    </div>
  );
};

interface ArrayRendererProps {
  items: any[];
}

const ArrayRenderer: React.FC<ArrayRendererProps> = ({ items }) => {
  if (items.length === 0) {
    return <div className="text-xs text-gray-600">No items found</div>;
  }

  // Check if all items are objects with consistent structure
  if (items.every(item => typeof item === 'object' && item !== null)) {
    return <TableRenderer items={items} />;
  }

  // Otherwise render as a simple list
  return (
    <ul className="text-xs text-green-700 space-y-1 list-disc list-inside">
      {items.map((item, idx) => (
        <li key={idx}>
          {typeof item === 'object' ? JSON.stringify(item) : String(item)}
        </li>
      ))}
    </ul>
  );
};

interface TableRendererProps {
  items: any[];
}

const TableRenderer: React.FC<TableRendererProps> = ({ items }) => {
  // Get all unique keys from all items
  const allKeys = new Set<string>();
  items.forEach(item => {
    if (typeof item === 'object' && item !== null) {
      Object.keys(item).forEach(key => allKeys.add(key));
    }
  });

  const keys = Array.from(allKeys);

  // Filter out very long keys or internal keys
  const displayKeys = keys.filter(key => {
    // Skip very long keys (like createdAt, updatedAt, supportedLanguages arrays)
    if (['createdAt', 'updatedAt', 'supportedLanguages', 'originalName', 'originalType'].includes(key)) {
      return false;
    }
    return true;
  });

  // If no keys after filtering, show first 5 keys
  const finalKeys = displayKeys.length > 0 ? displayKeys.slice(0, 6) : keys.slice(0, 4);

  return (
    <div className="overflow-x-auto">
      <table className="text-xs border-collapse border border-gray-300 w-full">
        <thead>
          <tr className="bg-gray-100">
            {finalKeys.map(key => (
              <th key={key} className="border border-gray-300 px-2 py-1 text-left font-semibold text-gray-700 whitespace-nowrap">
                {key}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {items.map((item, rowIdx) => (
            <tr key={rowIdx} className={rowIdx % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
              {finalKeys.map(key => (
                <td key={`${rowIdx}-${key}`} className="border border-gray-300 px-2 py-1 text-gray-700 max-w-xs truncate">
                  {renderCellValue(item[key])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {keys.length > finalKeys.length && (
        <div className="text-xs text-gray-500 mt-2">
          showing {finalKeys.length} of {keys.length} fields
        </div>
      )}
    </div>
  );
};

interface ObjectRendererProps {
  obj: any;
}

const ObjectRenderer: React.FC<ObjectRendererProps> = ({ obj }) => {
  const entries = Object.entries(obj).slice(0, 20); // Limit to 20 entries

  return (
    <div className="text-xs text-green-700 space-y-1">
      {entries.map(([key, value]) => (
        <div key={key} className="flex">
          <span className="font-semibold text-gray-700 min-w-32">{key}:</span>
          <span className="text-gray-600 ml-2">{renderCellValue(value)}</span>
        </div>
      ))}
      {Object.keys(obj).length > 20 && (
        <div className="text-gray-500 mt-2">+ {Object.keys(obj).length - 20} more fields</div>
      )}
    </div>
  );
};

/**
 * Render a cell value in a table, handling different types
 */
function renderCellValue(value: any): string {
  if (value === null || value === undefined) {
    return '—';
  }

  if (typeof value === 'boolean') {
    return value ? '✓' : '✗';
  }

  if (typeof value === 'string') {
    // Truncate long strings
    return value.length > 50 ? value.substring(0, 47) + '...' : value;
  }

  if (typeof value === 'number') {
    return String(value);
  }

  if (Array.isArray(value)) {
    return `[${value.length} items]`;
  }

  if (typeof value === 'object') {
    return '[Object]';
  }

  return String(value);
}

export default ExecutionResultRenderer;
