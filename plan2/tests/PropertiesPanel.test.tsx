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
