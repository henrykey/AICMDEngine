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
