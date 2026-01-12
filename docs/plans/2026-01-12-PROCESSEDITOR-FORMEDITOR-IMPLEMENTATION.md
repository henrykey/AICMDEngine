# ProcessEditor & FormEditor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build visual editors for BPMN processes and forms with real-time validation against Membership org data.

**Architecture:**
- ProcessEditor: React component using bpmn-js library for BPMN 2.0 canvas editing
- FormEditor: Custom React canvas with drag-drop form fields and permission binding
- Both integrate with backend validation (BPMNValidator, ExecutorPatternValidator)
- Real-time validation against Membership org/role/member data via API

**Tech Stack:** React 18 + TypeScript + Tailwind CSS, bpmn-js, custom canvas implementation

---

## Phase Overview

**Task 7: ProcessEditor** (3-4 days)
- BPMN canvas with drag-drop nodes
- Node property editing
- Real-time validation
- BPMN import/export

**Task 8: FormEditor** (3-4 days)
- Form field canvas with drag-drop
- Field property editing
- Permission rule editing
- Field-to-task binding

---

## Task 7: ProcessEditor Implementation

### 7.1: Setup bpmn-js and Create Canvas Component

**Files:**
- Modify: `plan2/package.json` - Add bpmn-js dependency
- Create: `plan2/src/components/ProcessEditor/ProcessEditor.tsx` - Main component
- Create: `plan2/src/components/ProcessEditor/index.ts` - Export
- Create: `plan2/src/types/bpmn.ts` - BPMN type definitions
- Create: `plan2/tests/ProcessEditor.test.tsx` - Tests

**Step 1: Add bpmn-js to package.json**

```json
{
  "dependencies": {
    "bpmn-js": "^14.2.0",
    "bpmn-moddle": "^14.0.0",
    "diagram-js": "^12.1.0",
    "diagram-js-direct-editing": "^2.5.0"
  }
}
```

Run: `cd plan2 && npm install`
Expected: All packages installed successfully

**Step 2: Create BPMN type definitions**

File: `plan2/src/types/bpmn.ts`

```typescript
export interface BPMNElement {
  id: string;
  type: string;
  name?: string;
  businessObject?: any;
}

export interface BPMNDefinition {
  id: string;
  targetNamespace: string;
  exporter: string;
  exporterVersion: string;
}

export interface ProcessEditorProps {
  bpmnXml?: string;
  onBpmnChange: (bpmnXml: string) => void;
  onValidationChange?: (validation: ValidationResult) => void;
  readOnly?: boolean;
}

export interface ValidationResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
}

export interface FormEditorProps {
  formJson?: FormDefinition;
  onFormChange: (form: FormDefinition) => void;
  bpmnXml?: string;
  onValidationChange?: (validation: ValidationResult) => void;
  readOnly?: boolean;
}

export interface FormDefinition {
  id: string;
  name: string;
  fields: FormField[];
}

export interface FormField {
  id: string;
  name: string;
  type: 'text' | 'number' | 'date' | 'select' | 'checkbox' | 'file';
  label: string;
  required: boolean;
  permissions?: PermissionRule[];
  taskBinding?: string; // BPMN task ID
  validationRules?: ValidationRule[];
}

export interface PermissionRule {
  action: 'view' | 'edit' | 'hide';
  subjects: string[]; // role:xxx or org:xxx or member:xxx
}

export interface ValidationRule {
  type: 'required' | 'minLength' | 'maxLength' | 'pattern' | 'custom';
  value?: any;
  message?: string;
}
```

**Step 3: Write failing test for ProcessEditor initialization**

File: `plan2/tests/ProcessEditor.test.tsx`

```typescript
import React from 'react';
import { render, screen } from '@testing-library/react';
import ProcessEditor from '../src/components/ProcessEditor/ProcessEditor';

describe('ProcessEditor', () => {
  it('should render BPMN canvas container', () => {
    const { container } = render(
      <ProcessEditor
        bpmnXml=""
        onBpmnChange={jest.fn()}
      />
    );

    const canvas = container.querySelector('[data-testid="bpmn-canvas"]');
    expect(canvas).toBeInTheDocument();
  });

  it('should initialize bpmn-js modeler', async () => {
    const { container } = render(
      <ProcessEditor
        bpmnXml=""
        onBpmnChange={jest.fn()}
      />
    );

    const modelerDiv = container.querySelector('[data-testid="bpmn-modeler"]');
    expect(modelerDiv).toBeInTheDocument();
  });

  it('should load BPMN XML on mount', async () => {
    const simpleBpmn = `<?xml version="1.0" encoding="UTF-8"?>
      <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Definitions_01">
        <bpmn:process id="Process_1" isExecutable="true">
          <bpmn:startEvent id="StartEvent_1" />
          <bpmn:endEvent id="EndEvent_1" />
        </bpmn:process>
      </bpmn:definitions>`;

    const { container } = render(
      <ProcessEditor
        bpmnXml={simpleBpmn}
        onBpmnChange={jest.fn()}
      />
    );

    const canvas = container.querySelector('[data-testid="bpmn-canvas"]');
    expect(canvas).toBeInTheDocument();
  });
});
```

Run: `cd plan2 && npm test -- ProcessEditor.test.tsx`
Expected: FAIL - ProcessEditor component not found

**Step 4: Implement ProcessEditor component (minimal)**

File: `plan2/src/components/ProcessEditor/ProcessEditor.tsx`

```typescript
import React, { useEffect, useRef } from 'react';
import BpmnModeler from 'bpmn-js/lib/Modeler';
import { ProcessEditorProps } from '../../types/bpmn';

const ProcessEditor: React.FC<ProcessEditorProps> = ({
  bpmnXml = '',
  onBpmnChange,
  onValidationChange,
  readOnly = false,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const modelerRef = useRef<BpmnModeler | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    // Initialize BPMN modeler
    const modeler = new BpmnModeler({
      container: containerRef.current,
      keyboard: { bindTo: document },
    });

    modelerRef.current = modeler;

    // Handle diagram changes
    modeler.on('commandStack.changed', async () => {
      try {
        const { xml } = await modeler.saveXML({ format: true });
        onBpmnChange(xml);
      } catch (err) {
        console.error('Failed to save BPMN:', err);
      }
    });

    // Load initial BPMN if provided
    if (bpmnXml) {
      modeler
        .importXML(bpmnXml)
        .then(() => {
          modeler.get('canvas').zoom('fit-viewport');
        })
        .catch((err) => {
          console.error('Failed to import BPMN:', err);
        });
    } else {
      // Create new process
      const newBpmn = `<?xml version="1.0" encoding="UTF-8"?>
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Definitions_01">
          <bpmn:process id="Process_1" isExecutable="true">
            <bpmn:startEvent id="StartEvent_1" name="Start" />
            <bpmn:endEvent id="EndEvent_1" name="End" />
          </bpmn:process>
        </bpmn:definitions>`;

      modeler.importXML(newBpmn).catch((err) => {
        console.error('Failed to create new BPMN:', err);
      });
    }

    return () => {
      modeler.destroy();
    };
  }, [bpmnXml, onBpmnChange]);

  return (
    <div className="w-full h-full flex flex-col">
      <div className="flex-1 overflow-hidden">
        <div
          data-testid="bpmn-canvas"
          ref={containerRef}
          className="w-full h-full"
          data-testid="bpmn-modeler"
        />
      </div>
    </div>
  );
};

export default ProcessEditor;
```

File: `plan2/src/components/ProcessEditor/index.ts`

```typescript
export { default } from './ProcessEditor';
export type { ProcessEditorProps } from '../../types/bpmn';
```

**Step 5: Run test to verify it passes**

Run: `cd plan2 && npm test -- ProcessEditor.test.tsx`
Expected: PASS (3/3 tests passing)

**Step 6: Commit**

```bash
cd /Users/kehongwei/workspace/AICMDEngine
git add plan2/package.json plan2/src/components/ProcessEditor/ plan2/src/types/bpmn.ts plan2/tests/ProcessEditor.test.tsx
git commit -m "feat: Add ProcessEditor component with bpmn-js integration"
```

---

### 7.2: Add Node Editing Properties Panel

**Files:**
- Create: `plan2/src/components/ProcessEditor/PropertiesPanel.tsx` - Node properties UI
- Create: `plan2/src/components/ProcessEditor/ExecutorConfigEditor.tsx` - Executor pattern config
- Modify: `plan2/src/components/ProcessEditor/ProcessEditor.tsx` - Integrate properties panel
- Create: `plan2/tests/PropertiesPanel.test.tsx` - Tests

**Step 1: Write test for properties panel**

File: `plan2/tests/PropertiesPanel.test.tsx`

```typescript
import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import PropertiesPanel from '../src/components/ProcessEditor/PropertiesPanel';

describe('PropertiesPanel', () => {
  const mockElement = {
    id: 'Task_1',
    type: 'bpmn:UserTask',
    businessObject: {
      id: 'Task_1',
      name: 'Approve Request',
    },
  };

  it('should render properties panel when element selected', () => {
    render(
      <PropertiesPanel
        element={mockElement}
        onPropertyChange={jest.fn()}
      />
    );

    expect(screen.getByText(/Properties/i)).toBeInTheDocument();
    expect(screen.getByDisplayValue('Task_1')).toBeInTheDocument();
  });

  it('should update name property', () => {
    const onChange = jest.fn();
    const { container } = render(
      <PropertiesPanel
        element={mockElement}
        onPropertyChange={onChange}
      />
    );

    const nameInput = container.querySelector('input[value="Approve Request"]') as HTMLInputElement;
    fireEvent.change(nameInput, { target: { value: 'New Name' } });

    expect(onChange).toHaveBeenCalledWith('name', 'New Name');
  });

  it('should show executor pattern selector for user tasks', () => {
    render(
      <PropertiesPanel
        element={mockElement}
        onPropertyChange={jest.fn()}
      />
    );

    expect(screen.getByText(/Executor Pattern/i)).toBeInTheDocument();
  });
});
```

Run: `cd plan2 && npm test -- PropertiesPanel.test.tsx`
Expected: FAIL - PropertiesPanel component not found

**Step 2: Implement PropertiesPanel component**

File: `plan2/src/components/ProcessEditor/PropertiesPanel.tsx`

```typescript
import React, { useState, useEffect } from 'react';
import ExecutorConfigEditor from './ExecutorConfigEditor';

interface PropertiesPanelProps {
  element: any;
  onPropertyChange: (property: string, value: any) => void;
}

const PropertiesPanel: React.FC<PropertiesPanelProps> = ({
  element,
  onPropertyChange,
}) => {
  const [name, setName] = useState(element?.businessObject?.name || '');
  const [executorPattern, setExecutorPattern] = useState(
    element?.businessObject?.documentation?.[0]?.text
  );

  useEffect(() => {
    setName(element?.businessObject?.name || '');
  }, [element?.id]);

  if (!element) {
    return (
      <div className="p-4 text-gray-500">
        Select an element to view properties
      </div>
    );
  }

  const handleNameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newName = e.target.value;
    setName(newName);
    onPropertyChange('name', newName);
  };

  const handleExecutorChange = (config: any) => {
    setExecutorPattern(config);
    onPropertyChange('executorPattern', config);
  };

  const isUserTask = element.type === 'bpmn:UserTask';

  return (
    <div className="w-80 bg-white border-l border-gray-300 p-4 overflow-y-auto max-h-screen">
      <h3 className="text-lg font-semibold mb-4">Properties</h3>

      {/* Element ID */}
      <div className="mb-4">
        <label className="block text-sm font-medium text-gray-700">ID</label>
        <input
          type="text"
          disabled
          value={element.id}
          className="mt-1 w-full px-3 py-2 border border-gray-300 rounded-md bg-gray-50"
        />
      </div>

      {/* Element Name */}
      <div className="mb-4">
        <label className="block text-sm font-medium text-gray-700">Name</label>
        <input
          type="text"
          value={name}
          onChange={handleNameChange}
          className="mt-1 w-full px-3 py-2 border border-gray-300 rounded-md"
        />
      </div>

      {/* Executor Pattern (only for user tasks) */}
      {isUserTask && (
        <div className="mb-4">
          <h4 className="text-sm font-medium text-gray-700 mb-2">Executor Pattern</h4>
          <ExecutorConfigEditor
            config={executorPattern}
            onChange={handleExecutorChange}
          />
        </div>
      )}
    </div>
  );
};

export default PropertiesPanel;
```

**Step 3: Implement ExecutorConfigEditor**

File: `plan2/src/components/ProcessEditor/ExecutorConfigEditor.tsx`

```typescript
import React, { useState } from 'react';

interface ExecutorConfigEditorProps {
  config?: any;
  onChange: (config: any) => void;
}

const EXECUTOR_PATTERNS = [
  'static',
  'form_driven',
  'dynamic',
  'queue_claim',
  'automation',
];

const ExecutorConfigEditor: React.FC<ExecutorConfigEditorProps> = ({
  config = {},
  onChange,
}) => {
  const [pattern, setPattern] = useState(config.executor_pattern || 'static');

  const handlePatternChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const newPattern = e.target.value;
    setPattern(newPattern);
    onChange({ executor_pattern: newPattern, executor_config: {} });
  };

  return (
    <div className="space-y-3">
      <select
        value={pattern}
        onChange={handlePatternChange}
        className="w-full px-3 py-2 border border-gray-300 rounded-md"
      >
        {EXECUTOR_PATTERNS.map((p) => (
          <option key={p} value={p}>
            {p.replace(/_/g, ' ').toUpperCase()}
          </option>
        ))}
      </select>

      <div className="text-xs text-gray-600 p-2 bg-gray-50 rounded">
        {pattern === 'static' && 'Assign to fixed role or department'}
        {pattern === 'form_driven' && 'Ask user to select executor at start'}
        {pattern === 'dynamic' && 'Route based on data analysis'}
        {pattern === 'queue_claim' && 'First available team member claims'}
        {pattern === 'automation' && 'Automated by MCP tool'}
      </div>
    </div>
  );
};

export default ExecutorConfigEditor;
```

**Step 4: Integrate properties panel into ProcessEditor**

Modify: `plan2/src/components/ProcessEditor/ProcessEditor.tsx`

Replace the return statement with:

```typescript
  const [selectedElement, setSelectedElement] = useState<any>(null);

  useEffect(() => {
    if (!modelerRef.current) return;

    const canvas = modelerRef.current.get('canvas');
    const eventBus = modelerRef.current.get('eventBus');

    eventBus.on('element.click', (event: any) => {
      setSelectedElement(event.element);
    });

    eventBus.on('canvas.viewbox.changed', () => {
      if (selectedElement && !canvas.getRootElement().children.includes(selectedElement)) {
        setSelectedElement(null);
      }
    });
  }, []);

  return (
    <div className="w-full h-full flex">
      <div className="flex-1 overflow-hidden">
        <div
          data-testid="bpmn-canvas"
          ref={containerRef}
          className="w-full h-full"
          data-testid="bpmn-modeler"
        />
      </div>
      <PropertiesPanel
        element={selectedElement}
        onPropertyChange={(prop, value) => {
          if (selectedElement && modelerRef.current) {
            const modeling = modelerRef.current.get('modeling');
            if (prop === 'name') {
              modeling.updateProperties(selectedElement, { name: value });
            }
          }
        }}
      />
    </div>
  );
```

Add import at top:

```typescript
import PropertiesPanel from './PropertiesPanel';
```

**Step 5: Run tests**

Run: `cd plan2 && npm test -- PropertiesPanel.test.tsx`
Expected: PASS (3/3 tests passing)

**Step 6: Commit**

```bash
git add plan2/src/components/ProcessEditor/ plan2/tests/PropertiesPanel.test.tsx
git commit -m "feat: Add properties panel for BPMN node editing"
```

---

### 7.3: Add Real-time Validation

**Files:**
- Create: `plan2/src/components/ProcessEditor/ValidationPanel.tsx` - Validation display
- Create: `plan2/src/services/bpmnValidator.ts` - Validation service
- Create: `plan2/tests/bpmnValidator.test.ts` - Validation tests

**Step 1: Write test for validation service**

File: `plan2/tests/bpmnValidator.test.ts`

```typescript
import { validateBpmn } from '../src/services/bpmnValidator';

describe('BPMN Validator', () => {
  const validBpmn = `<?xml version="1.0" encoding="UTF-8"?>
    <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Definitions_01">
      <bpmn:process id="Process_1" isExecutable="true">
        <bpmn:startEvent id="StartEvent_1" />
        <bpmn:userTask id="Task_1" name="Approve" />
        <bpmn:endEvent id="EndEvent_1" />
        <bpmn:sequenceFlow sourceRef="StartEvent_1" targetRef="Task_1" />
        <bpmn:sequenceFlow sourceRef="Task_1" targetRef="EndEvent_1" />
      </bpmn:process>
    </bpmn:definitions>`;

  it('should pass valid BPMN', async () => {
    const result = await validateBpmn(validBpmn);
    expect(result.valid).toBe(true);
    expect(result.errors).toHaveLength(0);
  });

  it('should detect missing start event', async () => {
    const invalidBpmn = validBpmn.replace('<bpmn:startEvent', '<!-- <bpmn:startEvent');
    const result = await validateBpmn(invalidBpmn);
    expect(result.valid).toBe(false);
    expect(result.errors.some((e) => e.includes('startEvent'))).toBe(true);
  });

  it('should detect missing end event', async () => {
    const invalidBpmn = validBpmn.replace('<bpmn:endEvent', '<!-- <bpmn:endEvent');
    const result = await validateBpmn(invalidBpmn);
    expect(result.valid).toBe(false);
    expect(result.errors.some((e) => e.includes('endEvent'))).toBe(true);
  });

  it('should detect broken sequence flows', async () => {
    const invalidBpmn = validBpmn.replace('targetRef="Task_1"', 'targetRef="NonExistent"');
    const result = await validateBpmn(invalidBpmn);
    expect(result.valid).toBe(false);
  });
});
```

Run: `cd plan2 && npm test -- bpmnValidator.test.ts`
Expected: FAIL - validateBpmn not found

**Step 2: Implement validation service**

File: `plan2/src/services/bpmnValidator.ts`

```typescript
import { ValidationResult } from '../types/bpmn';

export async function validateBpmn(bpmnXml: string): Promise<ValidationResult> {
  const errors: string[] = [];
  const warnings: string[] = [];

  try {
    // Parse XML
    const parser = new DOMParser();
    const doc = parser.parseFromString(bpmnXml, 'text/xml');

    if (doc.getElementsByTagName('parsererror').length > 0) {
      errors.push('Invalid XML syntax');
      return { valid: false, errors, warnings };
    }

    // Get process
    const processes = doc.getElementsByTagNameNS(
      'http://www.omg.org/spec/BPMN/20100524/MODEL',
      'process'
    );
    if (processes.length === 0) {
      errors.push('No BPMN process found');
      return { valid: false, errors, warnings };
    }

    const process = processes[0];

    // Check start event
    const startEvents = process.getElementsByTagNameNS(
      'http://www.omg.org/spec/BPMN/20100524/MODEL',
      'startEvent'
    );
    if (startEvents.length === 0) {
      errors.push('Process must have at least one start event');
    }

    // Check end event
    const endEvents = process.getElementsByTagNameNS(
      'http://www.omg.org/spec/BPMN/20100524/MODEL',
      'endEvent'
    );
    if (endEvents.length === 0) {
      errors.push('Process must have at least one end event');
    }

    // Validate sequence flows
    const flows = process.getElementsByTagNameNS(
      'http://www.omg.org/spec/BPMN/20100524/MODEL',
      'sequenceFlow'
    );
    const elementIds = new Set<string>();
    const allElements = process.querySelectorAll('[id]');
    allElements.forEach((el) => {
      elementIds.add(el.getAttribute('id') || '');
    });

    flows.forEach((flow) => {
      const sourceRef = flow.getAttribute('sourceRef');
      const targetRef = flow.getAttribute('targetRef');

      if (!elementIds.has(sourceRef || '')) {
        errors.push(`Sequence flow references non-existent source: ${sourceRef}`);
      }
      if (!elementIds.has(targetRef || '')) {
        errors.push(`Sequence flow references non-existent target: ${targetRef}`);
      }
    });
  } catch (err) {
    errors.push(`Validation error: ${err}`);
  }

  return {
    valid: errors.length === 0,
    errors,
    warnings,
  };
}

export async function validateBpmnWithServer(
  bpmnXml: string,
  tenantId: string
): Promise<ValidationResult> {
  try {
    const response = await fetch(`/api/v1/bpmn/validate`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Tenant-ID': tenantId,
      },
      body: JSON.stringify({ bpmn_xml: bpmnXml }),
    });

    if (!response.ok) {
      throw new Error(`Validation failed: ${response.statusText}`);
    }

    return await response.json();
  } catch (err) {
    return {
      valid: false,
      errors: [`Server validation error: ${err}`],
      warnings: [],
    };
  }
}
```

**Step 3: Create ValidationPanel component**

File: `plan2/src/components/ProcessEditor/ValidationPanel.tsx`

```typescript
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
```

**Step 4: Integrate validation into ProcessEditor**

Modify: `plan2/src/components/ProcessEditor/ProcessEditor.tsx`

Add validation state and effect:

```typescript
import { validateBpmn } from '../../services/bpmnValidator';

const [validation, setValidation] = useState<ValidationResult | null>(null);

useEffect(() => {
  if (bpmnXml) {
    validateBpmn(bpmnXml).then(setValidation);
  }
}, [bpmnXml]);
```

Add ValidationPanel to JSX:

```typescript
return (
  <div className="w-full h-full flex flex-col">
    <div className="flex-1 overflow-hidden flex">
      <div className="flex-1">
        <div ref={containerRef} className="w-full h-full" />
      </div>
      <PropertiesPanel element={selectedElement} onPropertyChange={...} />
    </div>
    <ValidationPanel validation={validation} />
  </div>
);
```

**Step 5: Run tests**

Run: `cd plan2 && npm test -- bpmnValidator.test.ts`
Expected: PASS (4/4 tests passing)

**Step 6: Commit**

```bash
git add plan2/src/services/ plan2/src/components/ProcessEditor/ValidationPanel.tsx plan2/tests/bpmnValidator.test.ts
git commit -m "feat: Add real-time BPMN validation"
```

---

## Task 8: FormEditor Implementation

### 8.1: Create Form Canvas Component

**Files:**
- Create: `plan2/src/components/FormEditor/FormEditor.tsx` - Main form editor
- Create: `plan2/src/components/FormEditor/FieldPalette.tsx` - Field types palette
- Create: `plan2/src/components/FormEditor/FormCanvas.tsx` - Drag-drop canvas
- Create: `plan2/src/components/FormEditor/index.ts` - Exports
- Create: `plan2/tests/FormEditor.test.tsx` - Tests

**Step 1: Write test for FormEditor**

File: `plan2/tests/FormEditor.test.tsx`

```typescript
import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import FormEditor from '../src/components/FormEditor/FormEditor';

describe('FormEditor', () => {
  const mockForm = {
    id: 'form_1',
    name: 'Approval Form',
    fields: [],
  };

  it('should render form editor with field palette', () => {
    render(
      <FormEditor
        formJson={mockForm}
        onFormChange={jest.fn()}
      />
    );

    expect(screen.getByText(/Field Types/i)).toBeInTheDocument();
  });

  it('should add field to form when dragged from palette', async () => {
    const onChange = jest.fn();
    render(
      <FormEditor
        formJson={mockForm}
        onFormChange={onChange}
      />
    );

    const textFieldButton = screen.getByText(/Text/i);
    fireEvent.click(textFieldButton);

    expect(onChange).toHaveBeenCalled();
  });

  it('should render empty canvas initially', () => {
    const { container } = render(
      <FormEditor
        formJson={mockForm}
        onFormChange={jest.fn()}
      />
    );

    const canvas = container.querySelector('[data-testid="form-canvas"]');
    expect(canvas).toBeInTheDocument();
  });
});
```

Run: `cd plan2 && npm test -- FormEditor.test.tsx`
Expected: FAIL - FormEditor not found

**Step 2: Implement FormEditor component**

File: `plan2/src/components/FormEditor/FormEditor.tsx`

```typescript
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
```

**Step 3: Implement FieldPalette**

File: `plan2/src/components/FormEditor/FieldPalette.tsx`

```typescript
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
```

**Step 4: Implement FormCanvas**

File: `plan2/src/components/FormEditor/FormCanvas.tsx`

```typescript
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
```

**Step 5: Export FormEditor**

File: `plan2/src/components/FormEditor/index.ts`

```typescript
export { default } from './FormEditor';
export { default as FieldPalette } from './FieldPalette';
export { default as FormCanvas } from './FormCanvas';
export type { FormEditorProps } from '../../types/bpmn';
```

**Step 6: Run tests**

Run: `cd plan2 && npm test -- FormEditor.test.tsx`
Expected: PASS (3/3 tests passing)

**Step 7: Commit**

```bash
git add plan2/src/components/FormEditor/ plan2/tests/FormEditor.test.tsx
git commit -m "feat: Add FormEditor component with field palette and canvas"
```

---

### 8.2: Add Field Property Editing and Permission Rules

**Files:**
- Create: `plan2/src/components/FormEditor/FieldPropertiesPanel.tsx` - Field properties
- Create: `plan2/src/components/FormEditor/PermissionRuleEditor.tsx` - Permission rules UI
- Modify: `plan2/src/components/FormEditor/FormEditor.tsx` - Integrate properties panel
- Create: `plan2/tests/FieldPropertiesPanel.test.tsx` - Tests

**Step 1: Write test for FieldPropertiesPanel**

File: `plan2/tests/FieldPropertiesPanel.test.tsx`

```typescript
import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import FieldPropertiesPanel from '../src/components/FormEditor/FieldPropertiesPanel';

describe('FieldPropertiesPanel', () => {
  const mockField = {
    id: 'field_1',
    name: 'approver',
    type: 'select' as const,
    label: 'Select Approver',
    required: true,
  };

  it('should render field properties', () => {
    render(
      <FieldPropertiesPanel
        field={mockField}
        onUpdate={jest.fn()}
      />
    );

    expect(screen.getByDisplayValue('Select Approver')).toBeInTheDocument();
    expect(screen.getByDisplayValue('approver')).toBeInTheDocument();
  });

  it('should update label', () => {
    const onChange = jest.fn();
    const { container } = render(
      <FieldPropertiesPanel
        field={mockField}
        onUpdate={onChange}
      />
    );

    const labelInput = screen.getByDisplayValue('Select Approver') as HTMLInputElement;
    fireEvent.change(labelInput, { target: { value: 'New Label' } });

    expect(onChange).toHaveBeenCalledWith({ label: 'New Label' });
  });

  it('should show permission rules section', () => {
    render(
      <FieldPropertiesPanel
        field={mockField}
        onUpdate={jest.fn()}
      />
    );

    expect(screen.getByText(/Permission Rules/i)).toBeInTheDocument();
  });
});
```

Run: `cd plan2 && npm test -- FieldPropertiesPanel.test.tsx`
Expected: FAIL

**Step 2: Implement FieldPropertiesPanel**

File: `plan2/src/components/FormEditor/FieldPropertiesPanel.tsx`

```typescript
import React, { useState } from 'react';
import { FormField } from '../../types/bpmn';
import PermissionRuleEditor from './PermissionRuleEditor';

interface FieldPropertiesPanelProps {
  field: FormField;
  onUpdate: (updates: Partial<FormField>) => void;
}

const FieldPropertiesPanel: React.FC<FieldPropertiesPanelProps> = ({
  field,
  onUpdate,
}) => {
  return (
    <div className="w-80 bg-white border-l border-gray-300 p-4 overflow-y-auto max-h-screen">
      <h3 className="text-lg font-semibold mb-4">Field Properties</h3>

      {/* Field Name */}
      <div className="mb-4">
        <label className="block text-sm font-medium text-gray-700">
          Field Name
        </label>
        <input
          type="text"
          value={field.name}
          onChange={(e) => onUpdate({ name: e.target.value })}
          className="mt-1 w-full px-3 py-2 border border-gray-300 rounded-md"
        />
      </div>

      {/* Label */}
      <div className="mb-4">
        <label className="block text-sm font-medium text-gray-700">
          Label
        </label>
        <input
          type="text"
          value={field.label}
          onChange={(e) => onUpdate({ label: e.target.value })}
          className="mt-1 w-full px-3 py-2 border border-gray-300 rounded-md"
        />
      </div>

      {/* Type */}
      <div className="mb-4">
        <label className="block text-sm font-medium text-gray-700">Type</label>
        <select
          value={field.type}
          onChange={(e) => onUpdate({ type: e.target.value as any })}
          className="mt-1 w-full px-3 py-2 border border-gray-300 rounded-md"
        >
          <option value="text">Text</option>
          <option value="number">Number</option>
          <option value="date">Date</option>
          <option value="select">Select</option>
          <option value="checkbox">Checkbox</option>
          <option value="file">File</option>
        </select>
      </div>

      {/* Required */}
      <div className="mb-4">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={field.required}
            onChange={(e) => onUpdate({ required: e.target.checked })}
          />
          <span className="text-sm font-medium text-gray-700">Required</span>
        </label>
      </div>

      {/* Permission Rules */}
      <div className="mb-4 pt-4 border-t border-gray-200">
        <h4 className="text-sm font-medium text-gray-700 mb-2">
          Permission Rules
        </h4>
        <PermissionRuleEditor
          permissions={field.permissions || []}
          onChange={(permissions) => onUpdate({ permissions })}
        />
      </div>
    </div>
  );
};

export default FieldPropertiesPanel;
```

**Step 3: Implement PermissionRuleEditor**

File: `plan2/src/components/FormEditor/PermissionRuleEditor.tsx`

```typescript
import React, { useState } from 'react';
import { PermissionRule } from '../../types/bpmn';

interface PermissionRuleEditorProps {
  permissions: PermissionRule[];
  onChange: (permissions: PermissionRule[]) => void;
}

const PermissionRuleEditor: React.FC<PermissionRuleEditorProps> = ({
  permissions = [],
  onChange,
}) => {
  const [newRule, setNewRule] = useState<PermissionRule>({
    action: 'view',
    subjects: [],
  });

  const handleAddRule = () => {
    if (newRule.subjects.length > 0) {
      onChange([...permissions, { ...newRule }]);
      setNewRule({ action: 'view', subjects: [] });
    }
  };

  const handleRemoveRule = (index: number) => {
    onChange(permissions.filter((_, i) => i !== index));
  };

  return (
    <div className="space-y-3">
      {/* Existing Rules */}
      {permissions.map((rule, index) => (
        <div key={index} className="p-2 bg-gray-50 rounded border border-gray-200">
          <div className="flex items-center justify-between mb-1">
            <span className="text-sm font-medium">{rule.action}</span>
            <button
              onClick={() => handleRemoveRule(index)}
              className="text-red-600 hover:bg-red-100 px-2 py-1 rounded text-xs"
            >
              Remove
            </button>
          </div>
          <div className="text-xs text-gray-600">
            {rule.subjects.join(', ')}
          </div>
        </div>
      ))}

      {/* Add New Rule */}
      <div className="p-2 bg-blue-50 rounded border border-blue-200">
        <div className="mb-2">
          <select
            value={newRule.action}
            onChange={(e) =>
              setNewRule({ ...newRule, action: e.target.value as any })
            }
            className="w-full px-2 py-1 text-sm border border-blue-300 rounded"
          >
            <option value="view">View</option>
            <option value="edit">Edit</option>
            <option value="hide">Hide</option>
          </select>
        </div>

        <div className="mb-2">
          <input
            type="text"
            placeholder="e.g., role:approver or org:finance"
            value={newRule.subjects.join(', ')}
            onChange={(e) =>
              setNewRule({
                ...newRule,
                subjects: e.target.value
                  .split(',')
                  .map((s) => s.trim())
                  .filter((s) => s),
              })
            }
            className="w-full px-2 py-1 text-sm border border-blue-300 rounded"
          />
        </div>

        <button
          onClick={handleAddRule}
          className="w-full px-2 py-1 text-sm bg-blue-500 text-white rounded hover:bg-blue-600"
        >
          Add Rule
        </button>
      </div>

      <p className="text-xs text-gray-500 mt-2">
        Format: role:name, org:name, or member:id
      </p>
    </div>
  );
};

export default PermissionRuleEditor;
```

**Step 4: Integrate into FormEditor**

Modify: `plan2/src/components/FormEditor/FormEditor.tsx`

Add properties panel column:

```typescript
import FieldPropertiesPanel from './FieldPropertiesPanel';

// In JSX, modify the layout to:
return (
  <div className="w-full h-full flex gap-4 p-4 bg-gray-50">
    <FieldPalette onAddField={handleAddField} />

    <div className="flex-1 flex flex-col">
      {/* Form name input */}
    </div>

    {selectedFieldId && (
      <FieldPropertiesPanel
        field={formJson.fields.find(f => f.id === selectedFieldId)!}
        onUpdate={(updates) => handleUpdateField(selectedFieldId, updates)}
      />
    )}
  </div>
);
```

**Step 5: Run tests**

Run: `cd plan2 && npm test -- FieldPropertiesPanel.test.tsx`
Expected: PASS (3/3 tests)

**Step 6: Commit**

```bash
git add plan2/src/components/FormEditor/ plan2/tests/FieldPropertiesPanel.test.tsx
git commit -m "feat: Add field properties panel with permission rules editor"
```

---

### 8.3: Add Field-to-Task Binding

**Files:**
- Create: `plan2/src/components/FormEditor/TaskBindingEditor.tsx` - Bind fields to BPMN tasks
- Modify: `plan2/src/components/FormEditor/FieldPropertiesPanel.tsx` - Add task binding section
- Create: `plan2/tests/TaskBindingEditor.test.tsx` - Tests

**Step 1: Write test for TaskBindingEditor**

File: `plan2/tests/TaskBindingEditor.test.tsx`

```typescript
import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import TaskBindingEditor from '../src/components/FormEditor/TaskBindingEditor';

describe('TaskBindingEditor', () => {
  const mockBpmn = `<?xml version="1.0"?>
    <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
      <bpmn:process id="Process_1">
        <bpmn:userTask id="Task_1" name="Approve" />
        <bpmn:userTask id="Task_2" name="Review" />
      </bpmn:process>
    </bpmn:definitions>`;

  it('should extract task names from BPMN', () => {
    render(
      <TaskBindingEditor
        bpmnXml={mockBpmn}
        currentBinding=""
        onBindingChange={jest.fn()}
      />
    );

    expect(screen.getByText(/Approve/)).toBeInTheDocument();
    expect(screen.getByText(/Review/)).toBeInTheDocument();
  });

  it('should update binding when task selected', () => {
    const onChange = jest.fn();
    render(
      <TaskBindingEditor
        bpmnXml={mockBpmn}
        currentBinding=""
        onBindingChange={onChange}
      />
    );

    const approveButton = screen.getByRole('button', { name: /Approve/ });
    fireEvent.click(approveButton);

    expect(onChange).toHaveBeenCalledWith('Task_1');
  });
});
```

Run: `cd plan2 && npm test -- TaskBindingEditor.test.tsx`
Expected: FAIL

**Step 2: Implement TaskBindingEditor**

File: `plan2/src/components/FormEditor/TaskBindingEditor.tsx`

```typescript
import React, { useMemo } from 'react';

interface TaskBindingEditorProps {
  bpmnXml?: string;
  currentBinding: string;
  onBindingChange: (taskId: string) => void;
}

interface BPMNTask {
  id: string;
  name: string;
}

const TaskBindingEditor: React.FC<TaskBindingEditorProps> = ({
  bpmnXml,
  currentBinding,
  onBindingChange,
}) => {
  const tasks = useMemo<BPMNTask[]>(() => {
    if (!bpmnXml) return [];

    try {
      const parser = new DOMParser();
      const doc = parser.parseFromString(bpmnXml, 'text/xml');

      const userTasks = doc.getElementsByTagNameNS(
        'http://www.omg.org/spec/BPMN/20100524/MODEL',
        'userTask'
      );

      const result: BPMNTask[] = [];
      userTasks.forEach((task) => {
        result.push({
          id: task.getAttribute('id') || '',
          name: task.getAttribute('name') || task.getAttribute('id') || '',
        });
      });

      return result;
    } catch (err) {
      console.error('Failed to parse BPMN:', err);
      return [];
    }
  }, [bpmnXml]);

  if (tasks.length === 0) {
    return (
      <p className="text-sm text-gray-500">
        No BPMN loaded or no user tasks found
      </p>
    );
  }

  return (
    <div className="space-y-2">
      <p className="text-sm font-medium text-gray-700">
        Bind this field to a task:
      </p>
      <div className="grid grid-cols-2 gap-2">
        {tasks.map((task) => (
          <button
            key={task.id}
            onClick={() => onBindingChange(task.id)}
            className={`p-2 text-sm rounded border transition ${
              currentBinding === task.id
                ? 'bg-green-100 border-green-500 font-medium'
                : 'bg-white border-gray-300 hover:border-gray-400'
            }`}
          >
            {task.name}
          </button>
        ))}
      </div>
    </div>
  );
};

export default TaskBindingEditor;
```

**Step 3: Add binding section to FieldPropertiesPanel**

Modify: `plan2/src/components/FormEditor/FieldPropertiesPanel.tsx`

Add import and section:

```typescript
import TaskBindingEditor from './TaskBindingEditor';

// Add to return JSX after Permission Rules:
{/* Task Binding */}
{bpmnXml && (
  <div className="mb-4 pt-4 border-t border-gray-200">
    <h4 className="text-sm font-medium text-gray-700 mb-2">
      Task Binding
    </h4>
    <TaskBindingEditor
      bpmnXml={bpmnXml}
      currentBinding={field.taskBinding || ''}
      onBindingChange={(taskId) => onUpdate({ taskBinding: taskId })}
    />
  </div>
)}
```

Add prop to interface:

```typescript
interface FieldPropertiesPanelProps {
  field: FormField;
  onUpdate: (updates: Partial<FormField>) => void;
  bpmnXml?: string;
}
```

**Step 4: Pass bpmnXml through FormEditor**

Modify: `plan2/src/components/FormEditor/FormEditor.tsx`

Update signature and pass through:

```typescript
export interface FormEditorProps {
  formJson?: FormDefinition;
  onFormChange: (form: FormDefinition) => void;
  bpmnXml?: string;
  onValidationChange?: (validation: ValidationResult) => void;
  readOnly?: boolean;
}

// In JSX:
{selectedFieldId && (
  <FieldPropertiesPanel
    field={formJson.fields.find(f => f.id === selectedFieldId)!}
    onUpdate={(updates) => handleUpdateField(selectedFieldId, updates)}
    bpmnXml={bpmnXml}
  />
)}
```

**Step 5: Run tests**

Run: `cd plan2 && npm test -- TaskBindingEditor.test.tsx`
Expected: PASS (2/2 tests)

**Step 6: Commit**

```bash
git add plan2/src/components/FormEditor/ plan2/tests/TaskBindingEditor.test.tsx
git commit -m "feat: Add field-to-task binding editor"
```

---

### 8.4: Add Form Validation

**Files:**
- Create: `plan2/src/services/formValidator.ts` - Form validation service
- Create: `plan2/src/components/FormEditor/FormValidationPanel.tsx` - Validation display
- Modify: `plan2/src/components/FormEditor/FormEditor.tsx` - Integrate validation
- Create: `plan2/tests/formValidator.test.ts` - Tests

**Step 1: Write test for form validator**

File: `plan2/tests/formValidator.test.ts`

```typescript
import { validateForm } from '../src/services/formValidator';
import { FormDefinition } from '../src/types/bpmn';

describe('Form Validator', () => {
  const validForm: FormDefinition = {
    id: 'form_1',
    name: 'Test Form',
    fields: [
      {
        id: 'field_1',
        name: 'approver',
        type: 'select',
        label: 'Approver',
        required: true,
      },
    ],
  };

  it('should pass valid form', () => {
    const result = validateForm(validForm);
    expect(result.valid).toBe(true);
    expect(result.errors).toHaveLength(0);
  });

  it('should detect duplicate field names', () => {
    const invalidForm: FormDefinition = {
      ...validForm,
      fields: [
        { ...validForm.fields[0], id: 'field_1' },
        { ...validForm.fields[0], id: 'field_2', name: 'approver' },
      ],
    };

    const result = validateForm(invalidForm);
    expect(result.valid).toBe(false);
    expect(result.errors.some((e) => e.includes('duplicate'))).toBe(true);
  });

  it('should detect invalid permission rules', () => {
    const invalidForm: FormDefinition = {
      ...validForm,
      fields: [
        {
          ...validForm.fields[0],
          permissions: [
            {
              action: 'view',
              subjects: ['invalid_format'],
            },
          ],
        },
      ],
    };

    const result = validateForm(invalidForm);
    expect(result.valid).toBe(false);
  });

  it('should warn about missing required field labels', () => {
    const warnForm: FormDefinition = {
      ...validForm,
      fields: [
        {
          ...validForm.fields[0],
          label: '',
        },
      ],
    };

    const result = validateForm(warnForm);
    expect(result.warnings.some((w) => w.includes('label'))).toBe(true);
  });
});
```

Run: `cd plan2 && npm test -- formValidator.test.ts`
Expected: FAIL

**Step 2: Implement formValidator service**

File: `plan2/src/services/formValidator.ts`

```typescript
import { FormDefinition, ValidationResult } from '../types/bpmn';

export function validateForm(form: FormDefinition): ValidationResult {
  const errors: string[] = [];
  const warnings: string[] = [];

  if (!form.name || form.name.trim() === '') {
    errors.push('Form name is required');
  }

  if (!form.fields || form.fields.length === 0) {
    warnings.push('Form has no fields');
  }

  // Check for duplicate field names
  const fieldNames = new Set<string>();
  form.fields.forEach((field) => {
    if (fieldNames.has(field.name)) {
      errors.push(`Duplicate field name: ${field.name}`);
    }
    fieldNames.add(field.name);

    // Check field properties
    if (!field.label || field.label.trim() === '') {
      warnings.push(`Field ${field.name} has no label`);
    }

    // Validate permission rules
    if (field.permissions && field.permissions.length > 0) {
      field.permissions.forEach((rule, index) => {
        if (!rule.subjects || rule.subjects.length === 0) {
          errors.push(
            `Permission rule ${index} in field ${field.name} has no subjects`
          );
        }

        rule.subjects.forEach((subject) => {
          if (!subject.match(/^(role|org|member):/)) {
            errors.push(
              `Invalid subject format in ${field.name}: "${subject}". Use role:, org:, or member: prefix`
            );
          }
        });
      });
    }
  });

  return {
    valid: errors.length === 0,
    errors,
    warnings,
  };
}
```

**Step 3: Implement FormValidationPanel**

File: `plan2/src/components/FormEditor/FormValidationPanel.tsx`

```typescript
import React from 'react';
import { ValidationResult } from '../../types/bpmn';

interface FormValidationPanelProps {
  validation: ValidationResult | null;
}

const FormValidationPanel: React.FC<FormValidationPanelProps> = ({
  validation,
}) => {
  if (!validation) {
    return null;
  }

  const { valid, errors, warnings } = validation;

  return (
    <div className={`p-4 border-t ${valid ? 'bg-green-50' : 'bg-red-50'}`}>
      <h4 className="font-semibold mb-2">
        {valid ? '✓ Valid Form' : '✗ Validation Errors'}
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

export default FormValidationPanel;
```

**Step 4: Integrate validation into FormEditor**

Modify: `plan2/src/components/FormEditor/FormEditor.tsx`

```typescript
import { validateForm } from '../../services/formValidator';
import FormValidationPanel from './FormValidationPanel';

// Add state:
const [validation, setValidation] = useState<ValidationResult | null>(null);

// Add effect:
useEffect(() => {
  setValidation(validateForm(formJson));
}, [formJson]);

// Modify return:
return (
  <div className="w-full h-full flex flex-col gap-4 p-4 bg-gray-50">
    <div className="flex gap-4 flex-1">
      <FieldPalette onAddField={handleAddField} />

      {/* Canvas area */}
    </div>

    <FormValidationPanel validation={validation} />
  </div>
);
```

**Step 5: Run tests**

Run: `cd plan2 && npm test -- formValidator.test.ts`
Expected: PASS (4/4 tests)

**Step 6: Commit**

```bash
git add plan2/src/services/formValidator.ts plan2/src/components/FormEditor/FormValidationPanel.tsx plan2/tests/formValidator.test.ts
git commit -m "feat: Add form validation with error and warning detection"
```

---

## Integration & E2E Testing

### 9.1: Create Example Workflow

**Files:**
- Create: `plan2/src/pages/WorkflowDesigner.tsx` - Main page integrating both editors
- Create: `plan2/tests/WorkflowDesigner.test.tsx` - Integration tests

**Step 1: Write integration test**

File: `plan2/tests/WorkflowDesigner.test.tsx`

```typescript
import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import WorkflowDesigner from '../src/pages/WorkflowDesigner';

describe('WorkflowDesigner Integration', () => {
  it('should render both editors', () => {
    const { container } = render(<WorkflowDesigner />);

    const bpmnCanvas = container.querySelector('[data-testid="bpmn-canvas"]');
    const formCanvas = container.querySelector('[data-testid="form-canvas"]');

    expect(bpmnCanvas).toBeInTheDocument();
    expect(formCanvas).toBeInTheDocument();
  });

  it('should save workflow', async () => {
    render(<WorkflowDesigner />);

    const saveButton = screen.getByRole('button', { name: /Save/i });
    fireEvent.click(saveButton);

    // Verify loading state or success message
    expect(screen.getByText(/saved|saving/i)).toBeInTheDocument();
  });
});
```

**Step 2: Implement WorkflowDesigner page**

File: `plan2/src/pages/WorkflowDesigner.tsx`

```typescript
import React, { useState } from 'react';
import ProcessEditor from '../components/ProcessEditor/ProcessEditor';
import FormEditor from '../components/FormEditor/FormEditor';
import { FormDefinition, ValidationResult } from '../types/bpmn';

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
```

**Step 3: Add route to App**

Modify: `plan2/src/App.tsx`

```typescript
import WorkflowDesigner from './pages/WorkflowDesigner';

// Add route:
<Route path="/designer" element={<WorkflowDesigner />} />
```

**Step 4: Run integration tests**

Run: `cd plan2 && npm test -- WorkflowDesigner.test.tsx`
Expected: PASS (2/2 tests)

**Step 5: Run full build**

Run: `cd plan2 && npm run build`
Expected: SUCCESS - No TypeScript errors, bundle created

**Step 6: Commit**

```bash
git add plan2/src/pages/WorkflowDesigner.tsx plan2/src/App.tsx plan2/tests/WorkflowDesigner.test.tsx
git commit -m "feat: Add WorkflowDesigner page integrating ProcessEditor and FormEditor"
```

---

## Summary

**Total Tasks: 9 implementation tasks + 1 integration**

**Bite-sized breakdown:**
- Task 7.1: bpmn-js setup + ProcessEditor canvas (1 day)
- Task 7.2: Properties panel + executor config editor (1 day)
- Task 7.3: Real-time validation (0.5 days)
- Task 8.1: FormEditor + FieldPalette + Canvas (1 day)
- Task 8.2: Field properties + permission rules (1 day)
- Task 8.3: Field-to-task binding (0.5 days)
- Task 8.4: Form validation (0.5 days)
- Task 9: WorkflowDesigner page integration (1 day)

**Estimated Timeline: 6-7 days**

**All tests use TDD (RED → GREEN → COMMIT):**
- ✓ Component tests
- ✓ Service tests
- ✓ Integration tests
- Expected: 30+ tests, all passing

---

**Plan saved to:** `/Users/kehongwei/workspace/AICMDEngine/docs/plans/2026-01-12-PROCESSEDITOR-FORMEDITOR-IMPLEMENTATION.md`
