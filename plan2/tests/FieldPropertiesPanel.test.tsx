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
