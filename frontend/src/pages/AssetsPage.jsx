import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Table, Tag } from 'antd';
import {
  ArrowLeftOutlined,
  DatabaseOutlined,
  GlobalOutlined,
  CloudServerOutlined,
} from '@ant-design/icons';
import api from '../services/api';
import '../styles/theme.css';

const AssetsPage = () => {
  const navigate = useNavigate();
  const [assets, setAssets] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchAssets = async () => {
      try {
        // Get all projects first
        const projectsResponse = await api.get('/dashboard/argus/overview');
        const projects = projectsResponse.data?.recent_projects || [];
        
        // Get assets from all projects
        let allAssets = [];
        for (const project of projects) {
          try {
            const assetsResponse = await api.get(`/projects/${project.id}/assets/`);
            if (assetsResponse.data) {
              const assetsWithProject = assetsResponse.data.map(asset => ({
                ...asset,
                projectName: project.name,
                projectId: project.id,
              }));
              allAssets = allAssets.concat(assetsWithProject);
            }
          } catch (error) {
            console.error(`Failed to fetch assets for project ${project.id}:`, error);
          }
        }
        
        setAssets(allAssets);
      } catch (error) {
        console.error('Failed to fetch assets:', error);
      } finally {
        setLoading(false);
      }
    };
    fetchAssets();
  }, []);

  const getAssetIcon = (type) => {
    switch (type) {
      case 'ip':
        return <DatabaseOutlined style={{ color: 'var(--accent-cyan)' }} />;
      case 'domain':
        return <GlobalOutlined style={{ color: 'var(--accent-blue)' }} />;
      case 'cloud_resource':
        return <CloudServerOutlined style={{ color: 'var(--accent-amber)' }} />;
      default:
        return <DatabaseOutlined style={{ color: 'var(--text-muted)' }} />;
    }
  };

  const getVerificationStatus = (status) => {
    const statusMap = {
      verified: { label: '已验证', color: 'var(--risk-low)' },
      pending: { label: '待验证', color: 'var(--accent-amber)' },
      failed: { label: '验证失败', color: 'var(--risk-high)' },
    };
    const s = statusMap[status] || statusMap.pending;
    return (
      <span style={{ color: s.color, fontSize: '10px', fontWeight: 700, letterSpacing: '0.5px' }}>
        ● {s.label}
      </span>
    );
  };

  const columns = [
    {
      title: '资产 ID',
      dataIndex: 'id',
      key: 'id',
      width: 100,
      render: (id) => (
        <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--accent-cyan)', fontSize: '11px' }}>
          A-{String(id).padStart(3, '0')}
        </span>
      ),
    },
    {
      title: '资产值',
      dataIndex: 'value',
      key: 'value',
      render: (value, record) => (
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {getAssetIcon(record.asset_type)}
          <span style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
            {value}
          </span>
        </div>
      ),
    },
    {
      title: '类型',
      dataIndex: 'asset_type',
      key: 'type',
      width: 120,
      render: (type) => {
        const typeLabels = { ip: 'IP', domain: '域名', cloud_resource: '云资源' };
        return (
          <span style={{ color: 'var(--text-secondary)', fontSize: '10px', fontWeight: 600, letterSpacing: '0.5px' }}>
            {typeLabels[type] || type}
          </span>
        );
      },
    },
    {
      title: '所属项目',
      dataIndex: 'projectName',
      key: 'project',
      width: 150,
      render: (name, record) => (
        <span 
          style={{ color: 'var(--accent-cyan)', fontSize: '11px', cursor: 'pointer' }}
          onClick={() => navigate(`/projects/${record.projectId}`)}
        >
          {name}
        </span>
      ),
    },
    {
      title: '验证状态',
      dataIndex: 'verification_status',
      key: 'verification',
      width: 120,
      render: (status) => getVerificationStatus(status),
    },
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      render: (name) => (
        <span style={{ color: 'var(--text-secondary)', fontSize: '11px' }}>
          {name || '-'}
        </span>
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
            资产管理
          </h1>
          <div style={{ color: 'var(--text-muted)', fontSize: '9px', marginTop: '2px', letterSpacing: '1px' }}>
            {assets.length} 个资产
          </div>
        </div>
      </div>

      {/* Assets Table */}
      <div className="argus-card" style={{ overflow: 'hidden', position: 'relative', zIndex: 1 }}>
        <Table
          columns={columns}
          dataSource={assets}
          rowKey="id"
          loading={loading}
          pagination={{
            pageSize: 20,
            showSizeChanger: false,
            style: { background: 'var(--bg-secondary)', padding: '12px' },
          }}
          style={{
            background: 'transparent',
          }}
        />
      </div>
    </div>
  );
};

export default AssetsPage;
