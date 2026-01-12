import { validateBpmn } from '../src/services/bpmnValidator';

describe('BPMN Validator', () => {
  const validBpmn = `<?xml version="1.0" encoding="UTF-8"?>
    <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Definitions_01">
      <bpmn:process id="Process_1" isExecutable="true">
        <bpmn:startEvent id="StartEvent_1" />
        <bpmn:userTask id="Task_1" name="Approve" />
        <bpmn:endEvent id="EndEvent_1" />
        <bpmn:sequenceFlow sourceRef="StartEvent_1" targetRef="Task_1" />
        <bpmn:sequenceFlow sourceRef="Task_1" targetRef="EndEvent_1" />
      </bpmn:process>
    </bpmn:definitions>`;

  it('should pass valid BPMN', async () => {
    const result = await validateBpmn(validBpmn);
    if (!result.valid) {
      console.log('Validation errors:', result.errors);
      console.log('Validation warnings:', result.warnings);
    }
    expect(result.valid).toBe(true);
    expect(result.errors).toHaveLength(0);
  });

  it('should detect missing start event', async () => {
    const invalidBpmn = validBpmn.replace('<bpmn:startEvent id="StartEvent_1" />', '');
    const result = await validateBpmn(invalidBpmn);
    expect(result.valid).toBe(false);
    expect(result.errors.some((e) => e.includes('start event'))).toBe(true);
  });

  it('should detect missing end event', async () => {
    const invalidBpmn = validBpmn.replace('<bpmn:endEvent id="EndEvent_1" />', '');
    const result = await validateBpmn(invalidBpmn);
    expect(result.valid).toBe(false);
    expect(result.errors.some((e) => e.includes('end event'))).toBe(true);
  });

  it('should detect broken sequence flows', async () => {
    const invalidBpmn = validBpmn.replace('targetRef="Task_1"', 'targetRef="NonExistent"');
    const result = await validateBpmn(invalidBpmn);
    expect(result.valid).toBe(false);
  });
});
