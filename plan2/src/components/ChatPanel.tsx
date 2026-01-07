import { useRef } from 'react';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
}

interface ChatPanelProps {
  commandSetId?: string;
}

const ChatPanel: React.FC<ChatPanelProps> = () => {
  const messages: Message[] = [
    {
      id: '1',
      role: 'assistant',
      content: '您好！我是AI助手。我可以帮助您分析数据、创建任务计划，并执行各种命令。',
      timestamp: new Date(Date.now() - 120000),
    },
    {
      id: '2',
      role: 'user',
      content: '请帮我创建一个数据处理流程，包括清洗、转换和分析步骤。',
      timestamp: new Date(Date.now() - 60000),
    },
    {
      id: '3',
      role: 'assistant',
      content: '好的！我已经为您创建了一个数据处理流程计划。包含以下任务：<br>1. 数据清洗（去除异常值和缺失值）<br>2. 特征工程（创建新特征）<br>3. 数据分析（生成统计报告）<br>4. 结果导出（保存为CSV文件）',
      timestamp: new Date(Date.now() - 30000),
    },
  ];

  const messagesEndRef = useRef<HTMLDivElement>(null);


  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="chat-messages flex flex-1 flex-col gap-5 overflow-y-auto pr-1">
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`max-w-[80%] p-3.5 rounded-2xl text-sm leading-relaxed shadow-sm ${
              msg.role === 'user'
                ? 'ml-auto rounded-br-none bg-blue-500 text-white'
                : 'rounded-bl-none bg-slate-100 text-slate-800'
            }`}
            dangerouslySetInnerHTML={{ __html: msg.content }}
          />
        ))}
        <div ref={messagesEndRef} />
      </div>
    </div>
  );
};

export default ChatPanel;