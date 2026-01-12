import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
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
    // Mock fetch
    global.fetch = jest.fn(() =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve({}),
      })
    ) as jest.Mock;

    // Mock alert
    global.alert = jest.fn();

    render(<WorkflowDesigner />);

    const saveButton = screen.getByRole('button', { name: /Save Workflow/i });
    fireEvent.click(saveButton);

    // Verify that fetch was called
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        '/api/v1/workflows',
        expect.objectContaining({
          method: 'POST',
        })
      );
    });
  });
});
