import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Table, Tag, Modal, Form, Input, Select, Button, Popconfirm, message } from 'antd';
import {
  ProjectOutlined,
  ArrowLeftOutlined,
  SearchOutlined,
  EditOutlined,
  DeleteOutlined,
} from '@ant-design/icons';
import api from '../services/api';
import '../styles/theme.css';

const ProjectsList = () => {
  const navigate = useNavigate();
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editingProject, setEditingProject] = useState(null);
  const [editModalVisible, setEditModalVisible] = useState(false);
  const [form] = Form.useForm();

  useEffect(() => {
    const fetchProjects = async () => {
      try {
        const response = await api.get('/dashboard/overview');
        setProjects(response.data.projects || []);
      } catch (error) {
        console.error('Failed to fetch projects:', error);
      } finally {
        setLoading(false);
      }
    };
    fetchProjects();
  }, []);

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
      // 重新获取项目列表
      const response = await api.get('/dashboard/overview');
      setProjects(response.data.projects || []);
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
      // 重新获取项目列表
      const response = await api.get('/dashboard/overview');
      setProjects(response.data.projects || []);
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
        <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--accent-cyan)', fontSize: '12px' }}>
          P-{String(id).padStart(3, '0')}
        </span>
      ),
    },
    {
      title: '项目名称',
      dataIndex: 'name',
      key: 'name',
      render: (name) => (
        <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>{name}</span>
      ),
    },
    {
      title: '等级',
      dataIndex: 'overall_status',
      key: 'level',
      width: 120,
      render: (_, record) => {
        const level = record.assessment_types?.[0]?.level || 'N/A';
        return (
          <span className={`risk-badge ${level === '三级' ? 'high' : level === '二级' ? 'medium' : 'low'}`}>
            {level}
          </span>
        );
      },
    },
    {
      title: '分数',
      dataIndex: 'overall_score',
      key: 'score',
      width: 100,
      render: (score) => (
        <span style={{
          fontFamily: 'var(--font-mono)',
          fontSize: '16px',
          fontWeight: 700,
          color: score >= 75 ? 'var(--risk-low)' : score >= 50 ? 'var(--risk-medium)' : 'var(--risk-high)',
        }}>
          {score !== null && score !== undefined ? Math.round(score) : '-'}
        </span>
      ),
    },
    {
      title: '状态',
      dataIndex: 'overall_status',
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
          <span style={{ color: s.color, fontSize: '11px', fontWeight: 600, letterSpacing: '0.5px' }}>
            ● {s.label}
          </span>
        );
      },
    },
    {
      title: '资产',
      dataIndex: 'asset_count',
      key: 'assets',
      width: 80,
      render: (count) => (
        <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>
          {count || 0}
        </span>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      render: (_, record) => (
        <div style={{ display: 'flex', gap: '8px' }} onClick={(e) => e.stopPropagation()}>
          <Button
            type="text"
            size="small"
            icon={<EditOutlined />}
            onClick={(e) => handleEdit(record, e)}
            style={{ color: 'var(--accent-cyan)' }}
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
              style={{ color: 'var(--risk-high)' }}
            />
          </Popconfirm>
        </div>
      ),
    },
  ];

  return (
    <div style={{ minHeight: '100vh', background: 'transparent', padding: '16px' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '16px', position: 'relative', zIndex: 1 }}>
        <button
          onClick={() => navigate('/')}
          style={{
            background: 'none',
            border: '1px solid var(--border-subtle)',
            color: 'var(--text-secondary)',
            padding: '6px 10px',
            borderRadius: '2px',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            fontSize: '10px',
            fontWeight: 600,
            letterSpacing: '1px',
          }}
        >
          <ArrowLeftOutlined /> 返回
        </button>
        <div>
          <h1 style={{
            color: 'var(--text-primary)',
            fontSize: '18px',
            fontWeight: 700,
            margin: 0,
            fontFamily: 'var(--font-mono)',
            letterSpacing: '2px',
          }}>
            项目管理
          </h1>
          <div style={{ color: 'var(--text-muted)', fontSize: '9px', marginTop: '2px', letterSpacing: '1px' }}>
            {projects.length} 个项目
          </div>
        </div>
      </div>

      {/* Projects Table */}
      <div className="argus-card" style={{ overflow: 'hidden' }}>
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
          style={{
            background: 'transparent',
          }}
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
