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
