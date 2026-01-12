const { validateBpmn } = require('./dist/services/bpmnValidator.js');

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

validateBpmn(validBpmn).then(result => {
  console.log('Result:', JSON.stringify(result, null, 2));
});
