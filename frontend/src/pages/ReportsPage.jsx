import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Table, Button } from 'antd';
import {
  ArrowLeftOutlined,
  FileTextOutlined,
  DownloadOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons';
import api from '../services/api';
import '../styles/theme.css';

const ReportsPage = () => {
  const navigate = useNavigate();
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchReports = async () => {
      try {
        // Get all projects
        const projectsResponse = await api.get('/dashboard/argus/overview');
        const projects = projectsResponse.data?.recent_projects || [];
        
        // Create report entries for each project
        const reportData = projects.map(project => ({
          id: project.id,
          projectName: project.name,
          level: project.compliance_level || 'N/A',
          score: project.compliance_score,
          status: project.compliance_score !== null && project.compliance_score !== undefined ? 'completed' : 'pending',
          updatedAt: project.updated_at,
        }));
        
        setReports(reportData);
      } catch (error) {
        console.error('Failed to fetch reports:', error);
      } finally {
        setLoading(false);
      }
    };
    fetchReports();
  }, []);

  const handleDownloadReport = async (projectId) => {
    try {
      const response = await api.get(`/projects/${projectId}/report`, {
        responseType: 'blob',
      });
      
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `compliance-report-${projectId}.pdf`);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (error) {
      console.error('Failed to download report:', error);
    }
  };

  const getStatusIcon = (status) => {
    if (status === 'completed') {
      return <CheckCircleOutlined style={{ color: 'var(--risk-low)' }} />;
    }
    return <ClockCircleOutlined style={{ color: 'var(--accent-amber)' }} />;
  };

  const columns = [
    {
      title: '报告 ID',
      dataIndex: 'id',
      key: 'id',
      width: 100,
      render: (id) => (
        <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--accent-cyan)', fontSize: '11px' }}>
          R-{String(id).padStart(3, '0')}
        </span>
      ),
    },
    {
      title: '项目名称',
      dataIndex: 'projectName',
      key: 'project',
      render: (name, record) => (
        <span 
          style={{ color: 'var(--text-primary)', fontSize: '12px', fontWeight: 500, cursor: 'pointer' }}
          onClick={() => navigate(`/projects/${record.id}`)}
        >
          {name}
        </span>
      ),
    },
    {
      title: '等级',
      dataIndex: 'level',
      key: 'level',
      width: 100,
      render: (level) => (
        <span className={`risk-badge ${level === '三级' ? 'high' : level === '二级' ? 'medium' : 'low'}`}>
          {level}
        </span>
      ),
    },
    {
      title: '分数',
      dataIndex: 'score',
      key: 'score',
      width: 100,
      render: (score) => (
        <span style={{
          fontFamily: 'var(--font-mono)',
          fontSize: '14px',
          fontWeight: 700,
          color: score >= 75 ? 'var(--risk-low)' : score >= 50 ? 'var(--risk-medium)' : 'var(--risk-high)',
        }}>
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
          pending: { label: '待处理', color: 'var(--accent-amber)' },
        };
        const s = statusMap[status] || statusMap.pending;
        return (
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            {getStatusIcon(status)}
            <span style={{ color: s.color, fontSize: '10px', fontWeight: 700, letterSpacing: '0.5px' }}>
              {s.label}
            </span>
          </div>
        );
      },
    },
    {
      title: '更新时间',
      dataIndex: 'updatedAt',
      key: 'updated',
      width: 150,
      render: (date) => (
        <span style={{ color: 'var(--text-muted)', fontSize: '10px', fontFamily: 'var(--font-mono)' }}>
          {date ? new Date(date).toLocaleDateString('zh-CN') : '-'}
        </span>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      render: (_, record) => (
        <Button
          size="small"
          icon={<DownloadOutlined />}
          onClick={() => handleDownloadReport(record.id)}
          disabled={record.status !== 'completed'}
          style={{
            background: record.status === 'completed' ? 'rgba(0, 212, 255, 0.1)' : 'transparent',
            border: '1px solid var(--border-subtle)',
            color: record.status === 'completed' ? 'var(--accent-cyan)' : 'var(--text-muted)',
            fontSize: '10px',
            fontWeight: 600,
            letterSpacing: '0.5px',
          }}
        >
          PDF
        </Button>
      ),
    },
  ];

  return (
    <div style={{ minHeight: '100vh', background: 'transparent', padding: '16px', position: 'relative' }}>
      {/* Background Logo Watermark */}
      <div className="bg-watermark" />
      
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
            报告中心
          </h1>
          <div style={{ color: 'var(--text-muted)', fontSize: '9px', marginTop: '2px', letterSpacing: '1px' }}>
            {reports.length} 份报告
          </div>
        </div>
      </div>

      {/* Reports Table */}
      <div className="argus-card" style={{ overflow: 'hidden', position: 'relative', zIndex: 1 }}>
        <Table
          columns={columns}
          dataSource={reports}
          rowKey="id"
          loading={loading}
          pagination={false}
          style={{
            background: 'transparent',
          }}
        />
      </div>
    </div>
  );
};

export default ReportsPage;
