import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Table, message } from 'antd';
import {
  ArrowLeftOutlined,
  DatabaseOutlined,
  GlobalOutlined,
  CloudServerOutlined,
} from '@ant-design/icons';
import api from '../services/api';
import { useAuthStore } from '../store/authStore';
import VeriSureLogo from '../components/VeriSureLogo';
import './OrganizationSettings.css';
import './CommandPages.css';

const AssetsPage = () => {
  const navigate = useNavigate();
  const [assets, setAssets] = useState([]);
  const [loading, setLoading] = useState(true);
  const currentOrgId = useAuthStore((state) => state.currentOrgId);

  useEffect(() => {
    const fetchAssets = async () => {
      if (!currentOrgId) return;
      setLoading(true);
      try {
        const projectsResponse = await api.get('/projects/', { params: { organization_id: currentOrgId } });
        const projects = projectsResponse.data || [];
        const assetGroups = await Promise.all(projects.map(async (project) => {
          try {
            const assetsResponse = await api.get(`/projects/${project.id}/assets/`);
            return (assetsResponse.data || []).map((asset) => ({
              ...asset,
              projectName: project.system_name || project.name,
              projectId: project.id,
            }));
          } catch (error) {
            console.error(`Failed to fetch assets for project ${project.id}:`, error);
            return [];
          }
        }));
        
        setAssets(assetGroups.flat());
      } catch (error) {
        console.error('Failed to fetch assets:', error);
        message.error?.('加载资产列表失败');
      } finally {
        setLoading(false);
      }
    };
    fetchAssets();
  }, [currentOrgId]);

  const getAssetIcon = (type) => {
    switch (type) {
      case 'ip':
        return <DatabaseOutlined className="command-asset-icon cyan" />;
      case 'domain':
        return <GlobalOutlined className="command-asset-icon blue" />;
      case 'cloud_resource':
        return <CloudServerOutlined className="command-asset-icon amber" />;
      default:
        return <DatabaseOutlined className="command-asset-icon muted" />;
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
      <span className="command-status" style={{ '--status-color': s.color }}>
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
        <span className="command-mono command-id">
          A-{String(id).padStart(3, '0')}
        </span>
      ),
    },
    {
      title: '资产值',
      dataIndex: 'value',
      key: 'value',
      render: (value, record) => (
        <div className="command-asset-value">
          {getAssetIcon(record.asset_type)}
          <span className="command-mono">
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
          <span className="command-muted">
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
          className="command-link"
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
        <span className="command-muted">
          {name || '-'}
        </span>
      ),
    },
  ];

  return (
    <div className="org-root command-page">
      <div className="org-bg-logo"><CloudServerOutlined /></div>
      <div className="org-bg-vignette" />

      <header className="org-header">
        <button className="org-back-btn" onClick={() => navigate('/dashboard')}>
          <ArrowLeftOutlined /> 返回 Dashboard
        </button>
        <div className="org-header-title">
          <VeriSureLogo size={28} />
          <div className="org-header-text">
            <span className="org-header-name">ASSET MATRIX</span>
            <span className="org-header-sub">// {assets.length} 个资产 · 跨项目归属视图</span>
          </div>
        </div>
      </header>

      <section className="org-section">
        <div className="org-section-header">
          <span className="org-section-tag">ASSETS</span>
          <span className="org-section-title">资产归属矩阵</span>
          <span className="org-section-meta">所有检测结果按资产与项目回溯</span>
        </div>
      </section>

      <div className="command-table-card">
        <Table
          columns={columns}
          dataSource={assets}
          rowKey="id"
          loading={loading}
          pagination={{
            pageSize: 20,
            showSizeChanger: false,
          }}
        />
      </div>
    </div>
  );
};

export default AssetsPage;
