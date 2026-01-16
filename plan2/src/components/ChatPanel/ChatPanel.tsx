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

// Real MCP AI response generator
async function generateAIResponse(
  prompt: string,
  _context: { bpmnXml: string; formDefinition: FormDefinition; selectedElement?: BpmnElement }
): Promise<{ content: string; generatedContent?: ChatMessage['generatedContent'] }> {
  console.log('🚀 generateAIResponse called with prompt:', prompt);

  try {
    // Call backend API which routes to real BPMN-MCP and FORM-MCP services
    const response = await fetch('/api/design/generate', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        prompt,
        context: _context,
      }),
    });

    if (!response.ok) {
      throw new Error(`API error: ${response.statusText}`);
    }

    const result = await response.json();
    console.log('📦 API Response:', result);

    // Build response based on what MCP returned
    let content = result.message || 'Content generated successfully';
    let generatedContent = result.generatedContent;

    // Ensure we have preview text
    if (generatedContent) {
      if (!generatedContent.preview) {
        if (generatedContent.type === 'bpmn') {
          generatedContent.preview = 'Generated workflow process';
        } else if (generatedContent.type === 'form') {
          // Handle both 'controls' (legacy) and 'fields' (current) property names
          const fieldCount = generatedContent.formDefinition?.fields?.length || generatedContent.formDefinition?.controls?.length || 0;
          generatedContent.preview = `Form with ${fieldCount} fields`;
        }
      }
    }

    return {
      content,
      generatedContent,
    };
  } catch (error) {
    console.error('❌ Error calling MCP services:', error);

    // Return error message
    return {
      content: `Error: ${error instanceof Error ? error.message : 'Failed to generate content'}. Please try again.`,
    };
  }
}

export default ChatPanel;
