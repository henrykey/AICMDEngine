import React from 'react';
import ReactMarkdown from 'react-markdown';
import MermaidBlock from './MermaidBlock';

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

  if (data && typeof data === 'object') {
    const markdown = typeof data.markdown === 'string' ? data.markdown : null;
    const mermaid = typeof data.mermaid === 'string' ? data.mermaid : null;
    if (markdown || mermaid) {
      const content = markdown || `\`\`\`mermaid\n${mermaid}\n\`\`\``;
      return (
        <div className="markdown-content">
          <ReactMarkdown
            components={{
              code({ inline, className, children, ...props }: any) {
                const match = /language-(\w+)/.exec(className || '');
                const code = String(children || '').replace(/\n$/, '');
                if (!inline && match?.[1] === 'mermaid') {
                  return <MermaidBlock chart={code} />;
                }
                return (
                  <code className={className} {...props}>
                    {children}
                  </code>
                );
              }
            }}
          >
            {content}
          </ReactMarkdown>
        </div>
      );
    }
  }

  // Handle arrays (list of items) - prioritize structured data over resultContent
  if (Array.isArray(data)) {
    return (
      <>
        {resultContent && <div className="text-xs text-green-700 mb-2">{resultContent}</div>}
        <ArrayRenderer items={data} />
      </>
    );
  }

  // Handle objects with 'data' field containing array (common API response pattern)
  if (data && typeof data === 'object' && Array.isArray(data.data)) {
    return (
      <>
        {resultContent && <div className="text-xs text-green-700 mb-2">{resultContent}</div>}
        <ArrayRenderer items={data.data} />
      </>
    );
  }

  // Handle objects with 'members' field (Membership API response)
  if (data && typeof data === 'object' && Array.isArray(data.members)) {
    return (
      <>
        {resultContent && <div className="text-xs text-green-700 mb-2">{resultContent}</div>}
        <ArrayRenderer items={data.members} />
      </>
    );
  }

  // Handle objects with 'roles' field
  if (data && typeof data === 'object' && Array.isArray(data.roles)) {
    return (
      <>
        {resultContent && <div className="text-xs text-green-700 mb-2">{resultContent}</div>}
        <ArrayRenderer items={data.roles} />
      </>
    );
  }

  // Handle objects with 'permissions' field (get_subject_permissions result)
  if (data && typeof data === 'object' && Array.isArray(data.permissions)) {
    return (
      <>
        {resultContent && <div className="text-xs text-green-700 mb-2">{resultContent}</div>}
        <ArrayRenderer items={data.permissions} />
      </>
    );
  }

  // Handle objects with 'effective_permissions' or 'member_roles' fields
  if (data && typeof data === 'object') {
    const hasExpandableList =
      Array.isArray(data.effective_permissions) ||
      Array.isArray(data.member_roles) ||
      Array.isArray(data.direct_permissions) ||
      Array.isArray(data.role_permissions) ||
      Array.isArray(data.permissions);

    if (hasExpandableList) {
      return <ObjectRenderer obj={data} />;
    }
  }

  // If we have result_content (human-readable summary) and no structured data, show that
  if (resultContent) {
    return (
      <div className="text-xs text-green-700 whitespace-pre-wrap leading-relaxed">
        {resultContent}
      </div>
    );
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
  const [showAll, setShowAll] = React.useState(false);
  const DISPLAY_LIMIT = 10;

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

  const displayItems = showAll ? items : items.slice(0, DISPLAY_LIMIT);

  return (
    <div>
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
            {displayItems.map((item, rowIdx) => (
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
      {items.length > DISPLAY_LIMIT && (
        <button
          onClick={() => setShowAll(!showAll)}
          className="text-xs text-blue-600 hover:text-blue-800 hover:underline mt-2 cursor-pointer"
        >
          {showAll ? `Show less` : `Show all ${items.length} items`}
        </button>
      )}
    </div>
  );
};

interface ObjectRendererProps {
  obj: any;
}

const ObjectRenderer: React.FC<ObjectRendererProps> = ({ obj }) => {
  const [expandedLists, setExpandedLists] = React.useState<Record<string, boolean>>({});
  const entries = Object.entries(obj).slice(0, 20);
  const LIST_DISPLAY_LIMIT = 10;

  const toggleList = (key: string) => {
    setExpandedLists(prev => ({ ...prev, [key]: !prev[key] }));
  };

  return (
    <div className="text-xs text-green-700 space-y-1">
      {entries.map(([key, value]) => {
        if (Array.isArray(value) && value.length > LIST_DISPLAY_LIMIT) {
          const displayList = expandedLists[key] ? value : value.slice(0, LIST_DISPLAY_LIMIT);
          return (
            <div key={key} className="flex flex-col">
              <div className="flex">
                <span className="font-semibold text-gray-700 min-w-32">{key}:</span>
                <span className="text-gray-600 ml-2">
                  [{displayList.length} items{expandedLists[key] ? '' : ` of ${value.length}`}
                  {expandedLists[key] ? '' : `, showing first ${LIST_DISPLAY_LIMIT}`}]
                </span>
              </div>
              <ul className="ml-32 text-gray-600 space-y-0.5">
                {displayList.map((item: any, idx: number) => (
                  <li key={idx}>
                    {typeof item === 'object' ? JSON.stringify(item) : String(item)}
                  </li>
                ))}
              </ul>
              <button
                onClick={() => toggleList(key)}
                className="text-xs text-blue-600 hover:text-blue-800 hover:underline mt-1 cursor-pointer self-start"
              >
                {expandedLists[key] ? `Show less` : `Show all ${value.length} items`}
              </button>
            </div>
          );
        }
        return (
          <div key={key} className="flex">
            <span className="font-semibold text-gray-700 min-w-32">{key}:</span>
            <span className="text-gray-600 ml-2">{renderCellValue(value)}</span>
          </div>
        );
      })}
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
    const label =
      value.fullName ||
      value.full_name ||
      value.name ||
      value.username ||
      value.code ||
      value.title ||
      value.id;
    if (label) {
      const suffix = value.id !== undefined && String(value.id) !== String(label) ? ` (ID: ${value.id})` : '';
      return `${label}${suffix}`;
    }
    return JSON.stringify(value);
  }

  return String(value);
}

export default ExecutionResultRenderer;
