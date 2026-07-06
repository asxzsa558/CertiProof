import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Table, Modal, Form, Input, Select, Button, Popconfirm, message } from 'antd';
import {
  ProjectOutlined,
  ArrowLeftOutlined,
  EditOutlined,
  DeleteOutlined,
} from '@ant-design/icons';
import api from '../services/api';
import { useAuthStore } from '../store/authStore';
import VeriSureLogo from '../components/VeriSureLogo';
import './OrganizationSettings.css';
import './CommandPages.css';

const ProjectsList = () => {
  const navigate = useNavigate();
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editingProject, setEditingProject] = useState(null);
  const [editModalVisible, setEditModalVisible] = useState(false);
  const [form] = Form.useForm();
  const currentOrgId = useAuthStore((state) => state.currentOrgId);

  const fetchProjects = async () => {
    if (!currentOrgId) return;
    setLoading(true);
    try {
      const [projectsRes, commandRes] = await Promise.all([
        api.get('/projects/', { params: { organization_id: currentOrgId } }),
        api.get('/dashboard/organization-command', { params: { organization_id: currentOrgId } }),
      ]);
      const matrixById = new Map((commandRes.data?.project_matrix || []).map((project) => [project.project_id, project]));
      setProjects((projectsRes.data || []).map((project) => ({
        ...project,
        command: matrixById.get(project.id) || {},
      })));
    } catch (error) {
      console.error('Failed to fetch projects:', error);
      message.error('加载项目列表失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchProjects();
  }, [currentOrgId]);

  const handleEdit = (project, e) => {
    e.stopPropagation();
    setEditingProject(project);
    form.setFieldsValue({
      name: project.name,
      description: project.description,
      system_name: project.system_name,
      status: project.status,
    });
    setEditModalVisible(true);
  };

  const handleUpdate = async () => {
    try {
      const values = await form.validateFields();
      await api.put(`/projects/${editingProject.id}`, values);
      message.success('项目更新成功');
      setEditModalVisible(false);
      fetchProjects();
    } catch (error) {
      console.error('Failed to update project:', error);
      message.error('更新失败：' + (error.response?.data?.detail || error.message));
    }
  };

  const handleDelete = async (projectId, e) => {
    e.stopPropagation();
    try {
      await api.delete(`/projects/${projectId}`);
      message.success('项目删除成功');
      fetchProjects();
    } catch (error) {
      console.error('Failed to delete project:', error);
      message.error('删除失败：' + (error.response?.data?.detail || error.message));
    }
  };

  const columns = [
    {
      title: '项目 ID',
      dataIndex: 'id',
      key: 'id',
      width: 100,
      render: (id) => (
        <span className="command-mono command-id">
          P-{String(id).padStart(3, '0')}
        </span>
      ),
    },
    {
      title: '项目名称',
      dataIndex: 'name',
      key: 'name',
      render: (name, record) => <span className="command-title">{record.system_name || name}</span>,
    },
    {
      title: '等级',
      key: 'level',
      width: 120,
      render: (_, record) => {
        const level = record.command?.level || record.compliance_level || '未定级';
        return (
          <span className={`risk-badge ${level === '三级' ? 'high' : level === '二级' ? 'medium' : 'low'}`}>
            {level}
          </span>
        );
      },
    },
    {
      title: '测评进度',
      key: 'progress',
      width: 130,
      render: (_, record) => {
        const value = record.command?.progress;
        return (
          <div className="command-progress-cell">
            <span>{value !== null && value !== undefined ? `${Math.round(value)}%` : '-'}</span>
            <b><i style={{ width: `${Math.max(0, Math.min(100, value || 0))}%` }} /></b>
          </div>
        )
      },
    },
    {
      title: '合规分数',
      dataIndex: 'compliance_score',
      key: 'score',
      width: 110,
      render: (score) => (
        <span className={`command-score ${(score || 0) >= 75 ? 'good' : (score || 0) >= 50 ? 'warn' : 'bad'}`}>
          {score !== null && score !== undefined ? Math.round(score) : '-'}
        </span>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 120,
      render: (status) => {
        const statusMap = {
          completed: { label: '已完成', color: 'var(--risk-low)' },
          in_progress: { label: '进行中', color: 'var(--accent-cyan)' },
          not_started: { label: '未开始', color: 'var(--text-muted)' },
        };
        const s = statusMap[status] || statusMap.not_started;
        return (
          <span className="command-status" style={{ '--status-color': s.color }}>
            ● {s.label}
          </span>
        );
      },
    },
    {
      title: '当前阶段',
      key: 'stage',
      width: 80,
      render: (_, record) => <span className="command-muted">{record.command?.stage || '未开始'}</span>,
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      render: (_, record) => (
        <div className="command-actions" onClick={(e) => e.stopPropagation()}>
          <Button
            type="text"
            size="small"
            icon={<EditOutlined />}
            onClick={(e) => handleEdit(record, e)}
            className="command-icon-button"
          />
          <Popconfirm
            title="确认删除"
            description="删除后无法恢复，确定要删除这个项目吗？"
            onConfirm={(e) => handleDelete(record.id, e)}
            onCancel={(e) => e.stopPropagation()}
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
          >
            <Button
              type="text"
              size="small"
              icon={<DeleteOutlined />}
              onClick={(e) => e.stopPropagation()}
              className="command-icon-button danger"
            />
          </Popconfirm>
        </div>
      ),
    },
  ];

  return (
    <div className="org-root command-page">
      <div className="org-bg-logo"><ProjectOutlined /></div>
      <div className="org-bg-vignette" />

      <header className="org-header">
        <button className="org-back-btn" onClick={() => navigate('/dashboard')}>
          <ArrowLeftOutlined /> 返回 Dashboard
        </button>
        <div className="org-header-title">
          <VeriSureLogo size={28} />
          <div className="org-header-text">
            <span className="org-header-name">PROJECT WORKSPACE</span>
            <span className="org-header-sub">// {projects.length} 个项目 · 组织级测评矩阵</span>
          </div>
        </div>
      </header>

      <section className="org-section">
        <div className="org-section-header">
          <span className="org-section-tag">PROJECTS</span>
          <span className="org-section-title">项目执行入口</span>
          <span className="org-section-meta">点击项目进入 AI 检测工作台</span>
        </div>
      </section>

      <div className="command-table-card">
        <Table
          columns={columns}
          dataSource={projects}
          rowKey="id"
          loading={loading}
          pagination={false}
          onRow={(record) => ({
            onClick: () => navigate(`/projects/${record.id}`),
            style: { cursor: 'pointer' },
          })}
        />
      </div>

      {/* Edit Modal */}
      <Modal
        title="编辑项目"
        open={editModalVisible}
        onOk={handleUpdate}
        onCancel={() => setEditModalVisible(false)}
        okText="保存"
        cancelText="取消"
      >
        <Form
          form={form}
          layout="vertical"
          style={{ marginTop: '16px' }}
        >
          <Form.Item
            name="name"
            label="项目名称"
            rules={[{ required: true, message: '请输入项目名称' }]}
          >
            <Input placeholder="请输入项目名称" />
          </Form.Item>
          <Form.Item
            name="system_name"
            label="系统名称"
          >
            <Input placeholder="请输入系统名称" />
          </Form.Item>
          <Form.Item
            name="description"
            label="项目描述"
          >
            <Input.TextArea rows={3} placeholder="请输入项目描述" />
          </Form.Item>
          <Form.Item
            name="status"
            label="项目状态"
          >
            <Select placeholder="选择项目状态">
              <Select.Option value="not_started">未开始</Select.Option>
              <Select.Option value="in_progress">进行中</Select.Option>
              <Select.Option value="completed">已完成</Select.Option>
            </Select>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default ProjectsList;
