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
