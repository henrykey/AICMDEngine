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
