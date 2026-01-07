import { useState } from 'react';

interface ExecutionStep {
  id: string;
  name: string;
  description: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
}

interface PlannerExecutorPanelProps {
  commandSetId?: string;
}

const PlannerExecutorPanel: React.FC<PlannerExecutorPanelProps> = () => {
  const [executionCommand, setExecutionCommand] = useState(
    'python feature_engineering.py --input cleaned_data.csv --output features/'
  );
  const [executionParams, setExecutionParams] = useState(`{
  "feature_generation": true,
  "feature_selection": true,
  "interaction_features": true,
  "polynomial_degree": 2,
  "variance_threshold": 0.01,
  "correlation_threshold": 0.85
}`);

  const executionSteps: ExecutionStep[] = [
    {
      id: '1',
      name: '数据清洗与预处理',
      description: '清理缺失值和异常值，标准化数据格式',
      status: 'completed',
    },
    {
      id: '2',
      name: '特征工程与选择',
      description: '生成交互特征并进行特征重要性排序',
      status: 'running',
    },
    {
      id: '3',
      name: '模型训练与评估',
      description: '使用XGBoost和Random Forest进行模型训练',
      status: 'pending',
    },
  ];

  const getStatusBgColor = (status: string) => {
    switch (status) {
      case 'completed':
        return 'bg-slate-50 border-l-4 border-green-500';
      case 'running':
        return 'bg-slate-50 border-l-4 border-blue-500';
      case 'pending':
        return 'bg-slate-50 border-l-4 border-amber-500';
      default:
        return 'bg-slate-50';
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'completed':
        return { bg: 'bg-green-100', text: 'text-green-800', label: '已完成' };
      case 'running':
        return { bg: 'bg-blue-100', text: 'text-blue-800', label: '进行中' };
      case 'pending':
        return { bg: 'bg-amber-100', text: 'text-amber-800', label: '待开始' };
      default:
        return { bg: 'bg-slate-100', text: 'text-slate-800', label: '未知' };
    }
  };

  const handleRun = () => {
    const cmd = executionCommand.trim();
    if (cmd) {
      console.log('执行命令:', cmd);
      alert('模拟执行：\n' + cmd);
    }
  };

  const handleClear = () => {
    setExecutionCommand('');
    setExecutionParams('');
  };

  return (
    <div className="flex flex-1 flex-col gap-6 overflow-y-auto">
      {/* 任务计划部分 */}
      <div>
        <div className="text-sm font-semibold text-slate-700 mb-3">任务计划</div>
        <div className="space-y-4">
          {executionSteps.map((step) => {
            const badge = getStatusBadge(step.status);
            return (
              <div
                key={step.id}
                className={`p-4 rounded-xl cursor-pointer hover:bg-slate-100 transition ${getStatusBgColor(step.status)}`}
              >
                <div className="flex justify-between">
                  <div className="font-medium text-slate-800">{step.name}</div>
                  <span className={`text-xs px-2 py-1 rounded ${badge.bg} ${badge.text}`}>
                    {badge.label}
                  </span>
                </div>
                <div className="text-sm text-slate-600 mt-1">{step.description}</div>
                <div className="mt-2 h-1.5 bg-slate-200 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full ${
                      step.status === 'completed'
                        ? 'bg-green-500 w-full'
                        : step.status === 'running'
                        ? 'bg-blue-500 w-2/3'
                        : 'bg-amber-500 w-0'
                    }`}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* 执行控制台部分 */}
      <div>
        <div className="text-sm font-semibold text-slate-700 mb-3">执行控制台</div>

        <div className="mb-4">
          <label className="block text-xs font-medium text-slate-700 mb-1.5">执行命令</label>
          <input
            type="text"
            value={executionCommand}
            onChange={(e) => setExecutionCommand(e.target.value)}
            className="w-full p-2.5 text-sm border border-slate-200 rounded-lg font-mono bg-slate-50 focus:bg-white focus:border-blue-500 focus:outline-none"
          />
        </div>

        <div className="mb-4">
          <label className="block text-xs font-medium text-slate-700 mb-1.5">参数配置 (JSON)</label>
          <textarea
            rows={4}
            value={executionParams}
            onChange={(e) => setExecutionParams(e.target.value)}
            className="w-full p-2.5 text-sm border border-slate-200 rounded-lg font-mono bg-slate-50 focus:bg-white focus:border-blue-500 focus:outline-none"
          />
        </div>

        <div className="flex gap-2">
          <button
            onClick={handleRun}
            className="flex-1 py-2 bg-gradient-to-r from-green-500 to-emerald-400 text-white text-sm rounded-lg font-medium flex items-center justify-center gap-1.5 hover:from-green-600 hover:to-emerald-500 transition"
          >
            <span>▶️</span> 执行
          </button>
          <button className="px-3 py-2 bg-slate-100 text-slate-700 text-sm rounded-lg font-medium hover:bg-slate-200 transition">
            ⏸️ 暂停
          </button>
          <button
            onClick={handleClear}
            className="px-3 py-2 bg-slate-100 text-slate-700 text-sm rounded-lg font-medium hover:bg-red-100 hover:text-red-600 transition"
          >
            🗑️ 清除
          </button>
        </div>
      </div>
    </div>
  );
};

export default PlannerExecutorPanel;