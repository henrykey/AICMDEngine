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
    <div className="w-full h-full flex flex-col" data-testid="bpmn-canvas">
      <div className="flex-1 overflow-hidden" data-testid="bpmn-modeler">
        <div
          ref={containerRef}
          className="w-full h-full"
        />
      </div>
    </div>
  );
};

export default ProcessEditor;
