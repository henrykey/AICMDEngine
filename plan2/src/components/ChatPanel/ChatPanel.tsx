/**
 * AI Chat Panel Component
 *
 * Provides AI-assisted workflow and form generation
 * Integrates with BPMN-MCP and FORM-MCP
 */

import React, { useState, useRef, useEffect } from 'react';
import { ChatMessage, FormDefinition, BpmnElement } from '../../types/workflow';

interface ChatPanelProps {
  collapsed: boolean;
  onToggleCollapse: () => void;
  messages: ChatMessage[];
  onMessagesChange: (messages: ChatMessage[]) => void;
  onApplyToProcess: (bpmnXml: string) => void;
  onApplyToForm: (formDef: FormDefinition) => void;
  currentContext: {
    bpmnXml: string;
    formDefinition: FormDefinition;
    selectedElement?: BpmnElement;
  };
}

const ChatPanel: React.FC<ChatPanelProps> = ({
  collapsed,
  onToggleCollapse,
  messages,
  onMessagesChange,
  onApplyToProcess,
  onApplyToForm,
  currentContext,
}) => {
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Handle send message
  const handleSend = async () => {
    if (!inputValue.trim() || isLoading) return;

    const userMessage: ChatMessage = {
      id: `msg-${Date.now()}`,
      role: 'user',
      content: inputValue.trim(),
      timestamp: new Date().toISOString(),
    };

    onMessagesChange([...messages, userMessage]);
    setInputValue('');
    setIsLoading(true);

    try {
      // Analyze intent and call appropriate MCP
      const response = await generateAIResponse(inputValue.trim(), currentContext);
      console.log('🔍 Chat Response:', response);
      console.log('📦 Generated Content:', response.generatedContent);

      const assistantMessage: ChatMessage = {
        id: `msg-${Date.now() + 1}`,
        role: 'assistant',
        content: response.content,
        timestamp: new Date().toISOString(),
        generatedContent: response.generatedContent,
      };

      console.log('💬 Assistant Message:', assistantMessage);
      onMessagesChange([...messages, userMessage, assistantMessage]);
    } catch (error) {
      const errorMessage: ChatMessage = {
        id: `msg-${Date.now() + 1}`,
        role: 'assistant',
        content: `Sorry, generation failed: ${error instanceof Error ? error.message : 'Unknown error'}`,
        timestamp: new Date().toISOString(),
      };
      onMessagesChange([...messages, userMessage, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  // Handle key press
  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // Handle apply generated content
  const handleApply = (message: ChatMessage) => {
    console.log('🎯 handleApply called for message:', message.id);
    console.log('  generatedContent:', message.generatedContent);

    if (!message.generatedContent) {
      console.log('  ❌ No generatedContent found!');
      return;
    }

    console.log('  hasBpmnXml:', !!message.generatedContent.bpmnXml);
    console.log('  hasFormDefinition:', !!message.generatedContent.formDefinition);

    if (message.generatedContent.bpmnXml) {
      console.log('  ✅ Calling onApplyToProcess with BPMN XML');
      onApplyToProcess(message.generatedContent.bpmnXml);
    }
    if (message.generatedContent.formDefinition) {
      console.log('  ✅ Calling onApplyToForm with form definition');
      onApplyToForm(message.generatedContent.formDefinition);
    }

    // Mark as applied
    const updatedMessages = messages.map(m =>
      m.id === message.id
        ? { ...m, actions: { ...m.actions, applied: true, appliedAt: new Date().toISOString() } }
        : m
    );
    console.log('  ✅ Marked message as applied, updating messages');
    onMessagesChange(updatedMessages);
  };

  // Collapsed view
  if (collapsed) {
    return (
      <div className="h-full flex flex-col items-center py-4">
        <button
          onClick={onToggleCollapse}
          className="p-2 text-gray-500 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition-colors"
          title="Expand AI Assistant"
        >
          <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
          </svg>
        </button>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="p-3 border-b border-gray-200 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <svg className="w-5 h-5 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
          </svg>
          <span className="font-medium text-gray-800">AI Assistant</span>
        </div>
        <button
          onClick={onToggleCollapse}
          className="p-1 text-gray-400 hover:text-gray-600 rounded"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 5l7 7-7 7M5 5l7 7-7 7" />
          </svg>
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {messages.length === 0 && (
          <div className="text-center text-gray-500 text-sm py-8">
            <p className="mb-2">Hello! I'm your AI Assistant</p>
            <p className="text-xs text-gray-400">
              Try saying "Generate an approval workflow" or "Create an expense request form"
            </p>
          </div>
        )}

        {messages.map((message) => (
          <MessageBubble
            key={message.id}
            message={message}
            onApply={() => handleApply(message)}
          />
        ))}

        {isLoading && (
          <div className="flex items-center gap-2 text-gray-500 text-sm">
            <div className="animate-spin w-4 h-4 border-2 border-blue-600 border-t-transparent rounded-full" />
            <span>AI is thinking...</span>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="p-3 border-t border-gray-200">
        <div className="flex gap-2">
          <textarea
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder="Describe the workflow or form you want..."
            className="flex-1 px-3 py-2 text-sm border border-gray-300 rounded-lg resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            rows={2}
            disabled={isLoading}
          />
          <button
            onClick={handleSend}
            disabled={!inputValue.trim() || isLoading}
            className="px-3 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
};

// Message Bubble Component
interface MessageBubbleProps {
  message: ChatMessage;
  onApply: () => void;
}

const MessageBubble: React.FC<MessageBubbleProps> = ({ message, onApply }) => {
  const isUser = message.role === 'user';
  const hasGeneratedContent = !!message.generatedContent;
  const isApplied = message.actions?.applied;

  console.log('🎯 MessageBubble render:', {
    messageId: message.id,
    role: message.role,
    hasGeneratedContent,
    generatedContentType: message.generatedContent?.type,
    isApplied,
  });

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[85%] rounded-lg px-3 py-2 ${
          isUser
            ? 'bg-blue-600 text-white'
            : 'bg-gray-100 text-gray-800'
        }`}
      >
        <p className="text-sm whitespace-pre-wrap">{message.content}</p>

        {/* Generated Content Preview */}
        {hasGeneratedContent && message.generatedContent?.preview && (
          <div className="mt-2 p-2 bg-white/10 rounded text-xs">
            <p className="opacity-80">{message.generatedContent.preview}</p>
          </div>
        )}
        {hasGeneratedContent && !message.generatedContent?.preview && (
          <div style={{ color: 'red' }}>DEBUG: Preview missing! Preview={message.generatedContent?.preview}</div>
        )}

        {/* Action Buttons */}
        {hasGeneratedContent && !isApplied && (
          <div className="mt-2 flex gap-2">
            <button
              onClick={onApply}
              className="px-2 py-1 text-xs bg-white/20 hover:bg-white/30 rounded transition-colors"
            >
              Apply to Canvas
            </button>
          </div>
        )}
        {hasGeneratedContent && isApplied && (
          <div style={{ color: 'orange' }}>DEBUG: Button hidden because isApplied={isApplied}</div>
        )}

        {/* Applied Badge */}
        {isApplied && (
          <div className="mt-2 flex items-center gap-1 text-xs opacity-70">
            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
            <span>Applied</span>
          </div>
        )}
      </div>
    </div>
  );
};

// Mock AI response generator (will be replaced with real MCP calls)
async function generateAIResponse(
  prompt: string,
  _context: { bpmnXml: string; formDefinition: FormDefinition; selectedElement?: BpmnElement }
): Promise<{ content: string; generatedContent?: ChatMessage['generatedContent'] }> {
  // Simulate API delay
  console.log('🚀 generateAIResponse called with prompt:', prompt);
  await new Promise(resolve => setTimeout(resolve, 1500));

  const lowerPrompt = prompt.toLowerCase();
  console.log('🔍 Lowercase prompt:', lowerPrompt);

  // Detect intent - prioritize form before process to avoid conflicts
  if (lowerPrompt.includes('表单') || lowerPrompt.includes('form')) {
    console.log('✅ Form detected');
    // Generate Form
    const mockForm: FormDefinition = {
      formId: `form-ai-${Date.now()}`,
      version: '1.0.0',
      title: 'AI Generated Form',
      description: 'Auto-generated form based on your requirements',
      controls: [
        {
          id: 'ctrl-1',
          type: 'text',
          label: 'Applicant Name',
          props: { placeholder: 'Enter your name', maxLength: 50 },
          width: '50%',
          permissions: {
            view: { condition: '*', appliesTo: ['*'] },
            edit: { condition: '*', appliesTo: ['*'] },
            required: { condition: 'true', appliesTo: ['*'] },
          },
        },
        {
          id: 'ctrl-2',
          type: 'select',
          label: 'Request Type',
          props: {
            options: [
              { label: 'Annual Leave', value: 'annual' },
              { label: 'Personal Leave', value: 'personal' },
              { label: 'Sick Leave', value: 'sick' },
            ],
          },
          width: '50%',
        },
        {
          id: 'ctrl-3',
          type: 'daterange',
          label: 'Leave Date',
          props: {},
          width: '100%',
        },
        {
          id: 'ctrl-4',
          type: 'textarea',
          label: 'Reason for Leave',
          props: { rows: 4, placeholder: 'Please specify the reason for leave' },
          width: '100%',
        },
      ],
      formType: 'task_bound',
      layout: { columns: 2, labelPosition: 'top' },
      confidenceScore: 0.85,
    };

    return {
      content: 'I\'ve generated a request form for you with fields for name, type, date range, and reason.',
      generatedContent: {
        type: 'form',
        formDefinition: mockForm,
        preview: 'Request form with 4 fields',
      },
    };
  }

  // Detect BPMN/process keywords
  if (lowerPrompt.includes('流程') || lowerPrompt.includes('审批') || lowerPrompt.includes('process') || lowerPrompt.includes('workflow') || lowerPrompt.includes('approval') || lowerPrompt.includes('submit')) {
    console.log('✅ BPMN/Process detected');
    // Generate BPMN with diagram information
    const mockBpmn = `<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" xmlns:di="http://www.omg.org/spec/DD/20100524/DI" id="Definitions_AI" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="Process_AI" name="AI Generated Process" isExecutable="true">
    <bpmn:startEvent id="Start_1" name="Start"/>
    <bpmn:userTask id="Task_1" name="Submit Request">
      <bpmn:documentation>{"executor_pattern": "static", "executor_config": {"type": "role", "value": "employee"}}</bpmn:documentation>
    </bpmn:userTask>
    <bpmn:userTask id="Task_2" name="Department Review">
      <bpmn:documentation>{"executor_pattern": "static", "executor_config": {"type": "role", "value": "manager"}}</bpmn:documentation>
    </bpmn:userTask>
    <bpmn:endEvent id="End_1" name="End"/>
    <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1"/>
    <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="Task_2"/>
    <bpmn:sequenceFlow id="Flow_3" sourceRef="Task_2" targetRef="End_1"/>
  </bpmn:process>
  <bpmndi:BPMNDiagram id="BPMNDiagram_1">
    <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="Process_AI">
      <bpmndi:BPMNShape id="Start_1_di" bpmnElement="Start_1">
        <dc:Bounds x="100" y="100" width="36" height="36"/>
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="Task_1_di" bpmnElement="Task_1">
        <dc:Bounds x="200" y="80" width="100" height="80"/>
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="Task_2_di" bpmnElement="Task_2">
        <dc:Bounds x="380" y="80" width="100" height="80"/>
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="End_1_di" bpmnElement="End_1">
        <dc:Bounds x="560" y="100" width="36" height="36"/>
      </bpmndi:BPMNShape>
      <bpmndi:BPMNEdge id="Flow_1_di" bpmnElement="Flow_1">
        <di:waypoint x="136" y="118"/>
        <di:waypoint x="200" y="120"/>
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Flow_2_di" bpmnElement="Flow_2">
        <di:waypoint x="300" y="120"/>
        <di:waypoint x="380" y="120"/>
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Flow_3_di" bpmnElement="Flow_3">
        <di:waypoint x="480" y="120"/>
        <di:waypoint x="560" y="118"/>
      </bpmndi:BPMNEdge>
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>
</bpmn:definitions>`;

    console.log('📋 Returning BPMN:', { type: 'bpmn', preview: 'Workflow with 2 approval nodes', hasBpmnXml: !!mockBpmn });
    return {
      content: 'I\'ve generated an approval workflow for you with submit request and department review nodes.',
      generatedContent: {
        type: 'bpmn',
        bpmnXml: mockBpmn,
        preview: 'Workflow with 2 approval nodes',
      },
    };
  }

  // Default response
  console.log('⚠️ No keywords matched, returning default response');
  return {
    content: 'I can help you with:\n• Generate BPMN workflows (say "Generate an approval workflow")\n• Create forms (say "Create a request form")\n• Modify existing workflows or forms\n\nWhat can I help you with?',
  };
}

export default ChatPanel;
