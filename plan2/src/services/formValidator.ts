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
      errors.push(`duplicate field name: ${field.name}`);
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
