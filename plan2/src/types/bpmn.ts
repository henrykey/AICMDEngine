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
