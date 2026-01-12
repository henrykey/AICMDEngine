import React, { useEffect, useRef, useState } from 'react';
import BpmnModeler from 'bpmn-js/lib/Modeler';
import { ProcessEditorProps, ValidationResult } from '../../types/bpmn';
import PropertiesPanel from './PropertiesPanel';
import ValidationPanel from './ValidationPanel';
import { validateBpmn } from '../../services/bpmnValidator';

const ProcessEditor: React.FC<ProcessEditorProps> = ({
  bpmnXml = '',
  onBpmnChange,
  onValidationChange: _onValidationChange,
  readOnly: _readOnly = false,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const modelerRef = useRef<BpmnModeler | null>(null);
  const [selectedElement, setSelectedElement] = useState<any>(null);
  const [validation, setValidation] = useState<ValidationResult | null>(null);

  useEffect(() => {
    if (!modelerRef.current) return;

    const canvas = modelerRef.current.get('canvas') as any;
    const eventBus = modelerRef.current.get('eventBus') as any;

    eventBus.on('element.click', (event: any) => {
      setSelectedElement(event.element);
    });

    eventBus.on('canvas.viewbox.changed', () => {
      if (selectedElement && !canvas.getRootElement().children.includes(selectedElement)) {
        setSelectedElement(null);
      }
    });
  }, [selectedElement]);

  useEffect(() => {
    if (bpmnXml) {
      validateBpmn(bpmnXml).then(setValidation);
    }
  }, [bpmnXml]);

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
        const result = await modeler.saveXML({ format: true }) as { xml: string };
        onBpmnChange(result.xml);
      } catch (err) {
        console.error('Failed to save BPMN:', err);
      }
    });

    // Load initial BPMN if provided
    if (bpmnXml) {
      modeler
        .importXML(bpmnXml)
        .then(() => {
          (modeler.get('canvas') as any).zoom('fit-viewport');
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
      <div className="flex-1 overflow-hidden flex">
        <div className="flex-1" data-testid="bpmn-modeler">
          <div
            ref={containerRef}
            className="w-full h-full"
          />
        </div>
        <PropertiesPanel
          element={selectedElement}
          onPropertyChange={(prop, value) => {
            if (selectedElement && modelerRef.current) {
              const modeling = modelerRef.current.get('modeling') as any;
              if (prop === 'name') {
                modeling.updateProperties(selectedElement, { name: value });
              }
            }
          }}
        />
      </div>
      <ValidationPanel validation={validation} />
    </div>
  );
};

export default ProcessEditor;
