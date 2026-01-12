import { ValidationResult } from '../types/bpmn';

export async function validateBpmn(bpmnXml: string): Promise<ValidationResult> {
  const errors: string[] = [];
  const warnings: string[] = [];

  try {
    // Parse XML
    const parser = new DOMParser();
    const doc = parser.parseFromString(bpmnXml, 'text/xml');

    if (doc.getElementsByTagName('parsererror').length > 0) {
      errors.push('Invalid XML syntax');
      return { valid: false, errors, warnings };
    }

    // Get process
    const processes = doc.getElementsByTagNameNS(
      'http://www.omg.org/spec/BPMN/20100524/MODEL',
      'process'
    );
    if (processes.length === 0) {
      errors.push('No BPMN process found');
      return { valid: false, errors, warnings };
    }

    const process = processes[0];

    // Check start event
    const startEvents = process.getElementsByTagNameNS(
      'http://www.omg.org/spec/BPMN/20100524/MODEL',
      'startEvent'
    );
    if (startEvents.length === 0) {
      errors.push('Process must have at least one start event');
    }

    // Check end event
    const endEvents = process.getElementsByTagNameNS(
      'http://www.omg.org/spec/BPMN/20100524/MODEL',
      'endEvent'
    );
    if (endEvents.length === 0) {
      errors.push('Process must have at least one end event');
    }

    // Validate sequence flows
    const flows = process.getElementsByTagNameNS(
      'http://www.omg.org/spec/BPMN/20100524/MODEL',
      'sequenceFlow'
    );
    const elementIds = new Set<string>();
    const allElements = process.querySelectorAll('[id]');
    allElements.forEach((el) => {
      elementIds.add(el.getAttribute('id') || '');
    });

    Array.from(flows).forEach((flow) => {
      const sourceRef = flow.getAttribute('sourceRef');
      const targetRef = flow.getAttribute('targetRef');

      if (!elementIds.has(sourceRef || '')) {
        errors.push(`Sequence flow references non-existent source: ${sourceRef}`);
      }
      if (!elementIds.has(targetRef || '')) {
        errors.push(`Sequence flow references non-existent target: ${targetRef}`);
      }
    });
  } catch (err) {
    errors.push(`Validation error: ${err}`);
  }

  return {
    valid: errors.length === 0,
    errors,
    warnings,
  };
}

export async function validateBpmnWithServer(
  bpmnXml: string,
  tenantId: string
): Promise<ValidationResult> {
  try {
    const response = await fetch(`/api/v1/bpmn/validate`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Tenant-ID': tenantId,
      },
      body: JSON.stringify({ bpmn_xml: bpmnXml }),
    });

    if (!response.ok) {
      throw new Error(`Validation failed: ${response.statusText}`);
    }

    return await response.json();
  } catch (err) {
    return {
      valid: false,
      errors: [`Server validation error: ${err}`],
      warnings: [],
    };
  }
}
