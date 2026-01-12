import React, { useMemo } from 'react';

interface TaskBindingEditorProps {
  bpmnXml?: string;
  currentBinding: string;
  onBindingChange: (taskId: string) => void;
}

interface BPMNTask {
  id: string;
  name: string;
}

const TaskBindingEditor: React.FC<TaskBindingEditorProps> = ({
  bpmnXml,
  currentBinding,
  onBindingChange,
}) => {
  const tasks = useMemo<BPMNTask[]>(() => {
    if (!bpmnXml) return [];

    try {
      const parser = new DOMParser();
      const doc = parser.parseFromString(bpmnXml, 'text/xml');

      const userTasks = doc.getElementsByTagNameNS(
        'http://www.omg.org/spec/BPMN/20100524/MODEL',
        'userTask'
      );

      const result: BPMNTask[] = [];
      Array.from(userTasks).forEach((task) => {
        result.push({
          id: task.getAttribute('id') || '',
          name: task.getAttribute('name') || task.getAttribute('id') || '',
        });
      });

      return result;
    } catch (err) {
      console.error('Failed to parse BPMN:', err);
      return [];
    }
  }, [bpmnXml]);

  if (tasks.length === 0) {
    return (
      <p className="text-sm text-gray-500">
        No BPMN loaded or no user tasks found
      </p>
    );
  }

  return (
    <div className="space-y-2">
      <p className="text-sm font-medium text-gray-700">
        Bind this field to a task:
      </p>
      <div className="grid grid-cols-2 gap-2">
        {tasks.map((task) => (
          <button
            key={task.id}
            onClick={() => onBindingChange(task.id)}
            className={`p-2 text-sm rounded border transition ${
              currentBinding === task.id
                ? 'bg-green-100 border-green-500 font-medium'
                : 'bg-white border-gray-300 hover:border-gray-400'
            }`}
          >
            {task.name}
          </button>
        ))}
      </div>
    </div>
  );
};

export default TaskBindingEditor;
