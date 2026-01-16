import React, { useEffect, useRef, useState, useCallback } from 'react';
import BpmnModeler from 'bpmn-js/lib/Modeler';
import { BpmnElement } from '../../types/workflow';

interface ProcessEditorProps {
  bpmnXml: string;
  onBpmnChange: (xml: string) => void;
  onElementSelect: (element: BpmnElement | null) => void;
  selectedElement: BpmnElement | null;
  validationMode: 'design' | 'production';
  readOnly?: boolean;
}

const ProcessEditor: React.FC<ProcessEditorProps> = ({
  bpmnXml = '',
  onBpmnChange,
  onElementSelect,
  selectedElement: _selectedElement,
  validationMode: _validationMode = 'design',
  readOnly: _readOnly = false,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const modelerRef = useRef<BpmnModeler | null>(null);
  const [internalSelectedElement, setInternalSelectedElement] = useState<any>(null);

  // Handle element selection
  const handleElementSelect = useCallback((element: any) => {
    setInternalSelectedElement(element);
    if (element) {
      const bpmnElement: BpmnElement = {
        id: element.id,
        type: element.type,
        name: element.businessObject?.name,
        businessObject: element.businessObject,
      };
      onElementSelect(bpmnElement);
    } else {
      onElementSelect(null);
    }
  }, [onElementSelect]);

  useEffect(() => {
    if (!modelerRef.current) return;

    const canvas = modelerRef.current.get('canvas') as any;
    const eventBus = modelerRef.current.get('eventBus') as any;

    eventBus.on('element.click', (event: any) => {
      handleElementSelect(event.element);
    });

    eventBus.on('canvas.viewbox.changed', () => {
      if (internalSelectedElement && !canvas.getRootElement().children.includes(internalSelectedElement)) {
        handleElementSelect(null);
      }
    });
  }, [internalSelectedElement, handleElementSelect]);

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
          // Use bpmn-js' built-in canvas for auto-fitting
          const canvas = modeler.get('canvas') as any;

          try {
            // Trigger auto-fit to arrange elements nicely
            canvas.zoom('fit-viewport', 'auto');
          } catch (e) {
            // Fallback to fixed zoom
            canvas.zoom(0.8);
          }
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

  // Handle property changes from parent
  const handlePropertyChange = useCallback((property: string, value: any) => {
    if (!modelerRef.current || !internalSelectedElement) return;

    const modeling = modelerRef.current.get('modeling') as any;
    const elementRegistry = modelerRef.current.get('elementRegistry') as any;
    const element = elementRegistry.get(internalSelectedElement.id);

    if (element) {
      modeling.updateProperties(element, { [property]: value });
    }
  }, [internalSelectedElement]);

  // Expose method to parent for property updates
  useEffect(() => {
    // Store the handler in a ref that parent can access if needed
    (window as any).__bpmnPropertyChangeHandler = handlePropertyChange;
    return () => {
      delete (window as any).__bpmnPropertyChangeHandler;
    };
  }, [handlePropertyChange]);

  return (
    <div className="w-full h-full flex flex-col" data-testid="bpmn-canvas">
      <div className="flex-1 overflow-hidden">
        <div
          ref={containerRef}
          className="w-full h-full"
          data-testid="bpmn-modeler"
        />
      </div>
    </div>
  );
};

export default ProcessEditor;
