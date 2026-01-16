/**
 * Membership Selector Modal
 *
 * Popup modal for selecting departments, roles, or members
 * Integrates with Membership MCP
 */

import React, { useState, useEffect } from 'react';
import { MembershipEntity, Department, Role, Member } from '../../types/workflow';

interface MembershipSelectorModalProps {
  open: boolean;
  onClose: () => void;
  mode: 'single' | 'multiple';
  allowedTypes: ('department' | 'role' | 'member')[];
  initialSelection?: MembershipEntity[];
  onConfirm: (selected: MembershipEntity[]) => void;
  title?: string;
}

type TabType = 'department' | 'role' | 'member';

const MembershipSelectorModal: React.FC<MembershipSelectorModalProps> = ({
  open,
  onClose,
  mode,
  allowedTypes,
  initialSelection = [],
  onConfirm,
  title = 'Select',
}) => {
  const [activeTab, setActiveTab] = useState<TabType>(allowedTypes[0]);
  const [searchQuery, setSearchQuery] = useState('');
  const [selected, setSelected] = useState<MembershipEntity[]>(initialSelection);
  const [loading, setLoading] = useState(false);

  // Mock data (will be replaced with MCP calls)
  const [departments, setDepartments] = useState<Department[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [members, setMembers] = useState<Member[]>([]);

  // Load data on open
  useEffect(() => {
    if (open) {
      loadData();
    }
  }, [open]);

  // Load membership data
  const loadData = async () => {
    setLoading(true);
    try {
      // Mock data - replace with actual MCP calls
      setDepartments([
        { id: 'dept-1', type: 'department', name: '技术部', memberCount: 15 },
        { id: 'dept-2', type: 'department', name: '财务部', memberCount: 8 },
        { id: 'dept-3', type: 'department', name: '人事部', memberCount: 5 },
        { id: 'dept-4', type: 'department', name: '市场部', memberCount: 12 },
        { id: 'dept-5', type: 'department', name: '运营部', memberCount: 10 },
      ]);

      setRoles([
        { id: 'role-1', type: 'role', name: '员工', description: '普通员工' },
        { id: 'role-2', type: 'role', name: '经理', description: '部门经理' },
        { id: 'role-3', type: 'role', name: '总监', description: '部门总监' },
        { id: 'role-4', type: 'role', name: '审批人', description: '审批人员' },
        { id: 'role-5', type: 'role', name: '管理员', description: '系统管理员' },
      ]);

      setMembers([
        { id: 'member-1', type: 'member', name: '张三', email: 'zhangsan@example.com', departmentId: 'dept-1', departmentName: '技术部', roles: ['员工'] },
        { id: 'member-2', type: 'member', name: '李四', email: 'lisi@example.com', departmentId: 'dept-1', departmentName: '技术部', roles: ['经理'] },
        { id: 'member-3', type: 'member', name: '王五', email: 'wangwu@example.com', departmentId: 'dept-2', departmentName: '财务部', roles: ['员工'] },
        { id: 'member-4', type: 'member', name: '赵六', email: 'zhaoliu@example.com', departmentId: 'dept-2', departmentName: '财务部', roles: ['经理', '审批人'] },
      ]);
    } catch (error) {
      console.error('Failed to load membership data:', error);
    } finally {
      setLoading(false);
    }
  };

  // Handle selection toggle
  const toggleSelection = (entity: MembershipEntity) => {
    if (mode === 'single') {
      setSelected([entity]);
    } else {
      const isSelected = selected.some(s => s.id === entity.id);
      if (isSelected) {
        setSelected(selected.filter(s => s.id !== entity.id));
      } else {
        setSelected([...selected, entity]);
      }
    }
  };

  // Check if entity is selected
  const isSelected = (entity: MembershipEntity) => {
    return selected.some(s => s.id === entity.id);
  };

  // Filter by search query
  const filterBySearch = <T extends MembershipEntity>(items: T[]): T[] => {
    if (!searchQuery) return items;
    return items.filter(item =>
      item.name.toLowerCase().includes(searchQuery.toLowerCase())
    );
  };

  // Handle confirm
  const handleConfirm = () => {
    onConfirm(selected);
    onClose();
  };

  if (!open) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/50 z-50"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="fixed inset-0 flex items-center justify-center z-50 p-4">
        <div
          className="bg-white rounded-lg shadow-xl w-full max-w-lg max-h-[80vh] flex flex-col"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="p-4 border-b border-gray-200 flex items-center justify-between">
            <h3 className="text-lg font-semibold text-gray-800">{title}</h3>
            <button
              onClick={onClose}
              className="p-1 text-gray-400 hover:text-gray-600 rounded"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          {/* Search */}
          <div className="p-4 border-b border-gray-200">
            <div className="relative">
              <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search..."
                className="w-full pl-10 pr-4 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>

          {/* Tabs */}
          <div className="flex border-b border-gray-200">
            {allowedTypes.includes('department') && (
              <TabButton
                active={activeTab === 'department'}
                onClick={() => setActiveTab('department')}
              >
                Department
              </TabButton>
            )}
            {allowedTypes.includes('role') && (
              <TabButton
                active={activeTab === 'role'}
                onClick={() => setActiveTab('role')}
              >
                Role
              </TabButton>
            )}
            {allowedTypes.includes('member') && (
              <TabButton
                active={activeTab === 'member'}
                onClick={() => setActiveTab('member')}
              >
                Member
              </TabButton>
            )}
          </div>

          {/* Content */}
          <div className="flex-1 overflow-y-auto p-4">
            {loading ? (
              <div className="flex items-center justify-center py-8">
                <div className="animate-spin w-6 h-6 border-2 border-blue-600 border-t-transparent rounded-full" />
              </div>
            ) : (
              <>
                {activeTab === 'department' && (
                  <div className="space-y-2">
                    {filterBySearch(departments).map(dept => (
                      <SelectableItem
                        key={dept.id}
                        entity={dept}
                        selected={isSelected(dept)}
                        onToggle={() => toggleSelection(dept)}
                        icon={
                          <svg className="w-5 h-5 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
                          </svg>
                        }
                        subtitle={`${dept.memberCount} people`}
                      />
                    ))}
                  </div>
                )}

                {activeTab === 'role' && (
                  <div className="space-y-2">
                    {filterBySearch(roles).map(role => (
                      <SelectableItem
                        key={role.id}
                        entity={role}
                        selected={isSelected(role)}
                        onToggle={() => toggleSelection(role)}
                        icon={
                          <svg className="w-5 h-5 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                          </svg>
                        }
                        subtitle={role.description}
                      />
                    ))}
                  </div>
                )}

                {activeTab === 'member' && (
                  <div className="space-y-2">
                    {filterBySearch(members).map(member => (
                      <SelectableItem
                        key={member.id}
                        entity={member}
                        selected={isSelected(member)}
                        onToggle={() => toggleSelection(member)}
                        icon={
                          <svg className="w-5 h-5 text-purple-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                          </svg>
                        }
                        subtitle={`${member.departmentName} · ${member.roles.join(', ')}`}
                      />
                    ))}
                  </div>
                )}
              </>
            )}
          </div>

          {/* Selected Items */}
          {selected.length > 0 && (
            <div className="p-4 border-t border-gray-200 bg-gray-50">
              <p className="text-xs text-gray-500 mb-2">Selected ({selected.length})</p>
              <div className="flex flex-wrap gap-2">
                {selected.map(entity => (
                  <span
                    key={entity.id}
                    className="inline-flex items-center gap-1 px-2 py-1 bg-blue-100 text-blue-700 rounded text-sm"
                  >
                    {entity.name}
                    <button
                      onClick={() => toggleSelection(entity)}
                      className="hover:text-blue-900"
                    >
                      <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Footer */}
          <div className="p-4 border-t border-gray-200 flex justify-end gap-3">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800 hover:bg-gray-100 rounded-lg transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleConfirm}
              disabled={selected.length === 0}
              className="px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
            >
              Confirm
            </button>
          </div>
        </div>
      </div>
    </>
  );
};

// Tab Button
interface TabButtonProps {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}

const TabButton: React.FC<TabButtonProps> = ({ active, onClick, children }) => (
  <button
    onClick={onClick}
    className={`flex-1 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
      active
        ? 'border-blue-600 text-blue-600'
        : 'border-transparent text-gray-500 hover:text-gray-700'
    }`}
  >
    {children}
  </button>
);

// Selectable Item
interface SelectableItemProps {
  entity: MembershipEntity;
  selected: boolean;
  onToggle: () => void;
  icon: React.ReactNode;
  subtitle?: string;
}

const SelectableItem: React.FC<SelectableItemProps> = ({
  entity,
  selected,
  onToggle,
  icon,
  subtitle,
}) => (
  <div
    onClick={onToggle}
    className={`flex items-center gap-3 p-3 rounded-lg cursor-pointer transition-all ${
      selected
        ? 'bg-blue-50 border border-blue-200'
        : 'bg-white border border-gray-200 hover:border-gray-300'
    }`}
  >
    <div className="flex-shrink-0">{icon}</div>
    <div className="flex-1 min-w-0">
      <p className="font-medium text-gray-800 truncate">{entity.name}</p>
      {subtitle && (
        <p className="text-xs text-gray-500 truncate">{subtitle}</p>
      )}
    </div>
    <div
      className={`w-5 h-5 rounded border flex items-center justify-center flex-shrink-0 ${
        selected
          ? 'bg-blue-600 border-blue-600'
          : 'border-gray-300'
      }`}
    >
      {selected && (
        <svg className="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
        </svg>
      )}
    </div>
  </div>
);

export default MembershipSelectorModal;
