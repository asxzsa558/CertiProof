import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Layout, Menu, Avatar, Dropdown } from 'antd';
import {
  DashboardOutlined,
  ProjectOutlined,
  DatabaseOutlined,
  FileTextOutlined,
  SettingOutlined,
  UserOutlined,
  LogoutOutlined,
  BellOutlined,
} from '@ant-design/icons';
import { useAuthStore } from '../store/authStore';
import ComplianceScoreTrend from '../components/dashboard/ComplianceScoreTrend';
import ActiveAssessments from '../components/dashboard/ActiveAssessments';
import AssetDistribution from '../components/dashboard/AssetDistribution';
import RiskHeatmap from '../components/dashboard/RiskHeatmap';
import VeriSureLogo from '../components/VeriSureLogo';
import '../styles/theme.css';
import './Dashboard.css';

const { Header, Sider, Content } = Layout;

// Error Boundary Component
class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('Dashboard component error:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ 
          padding: '16px', 
          background: 'var(--risk-high)', 
          color: 'white', 
          borderRadius: '8px',
          margin: '16px'
        }}>
          <h3>Component Error</h3>
          <p>{this.state.error?.message}</p>
        </div>
      );
    }
    return this.props.children;
  }
}

const Dashboard = () => {
  const navigate = useNavigate();
  const user = useAuthStore((state) => state.user);
  const logout = useAuthStore((state) => state.logout);
  const [currentTime, setCurrentTime] = useState(new Date());

  useEffect(() => {
    const timer = setInterval(() => {
      setCurrentTime(new Date());
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const userMenu = {
    items: [
      {
        key: 'profile',
        icon: <UserOutlined />,
        label: 'Profile',
      },
      {
        key: 'logout',
        icon: <LogoutOutlined />,
        label: 'Logout',
        onClick: handleLogout,
      },
    ],
  };

  return (
    <Layout style={{ minHeight: '100vh', background: 'var(--bg-primary)', position: 'relative' }}>
      
      {/* Top Navigation */}
      <Header style={{ 
        background: 'var(--bg-secondary)', 
        borderBottom: '1px solid var(--border-subtle)',
        padding: '0 20px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        height: '56px',
        position: 'relative',
        zIndex: 10,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <VeriSureLogo size={56} />
          <div style={{ 
            fontSize: '28px', 
            fontWeight: '700', 
            color: 'var(--accent-cyan)',
            fontFamily: 'var(--font-mono)',
            letterSpacing: '2px',
          }}>
            VERISURE
          </div>
          <div style={{ display: 'flex', gap: '24px', marginLeft: '32px' }}>
            <span 
              style={{ color: 'var(--accent-cyan)', fontSize: '13px', fontWeight: '600', borderBottom: '2px solid var(--accent-cyan)', paddingBottom: '4px', cursor: 'pointer' }}
              onClick={() => navigate('/')}
            >
              概览
            </span>
            <span 
              style={{ color: 'var(--text-secondary)', fontSize: '13px', cursor: 'pointer' }} 
              onClick={() => navigate('/projects')}
            >
              项目管理
            </span>
            <span 
              style={{ color: 'var(--text-secondary)', fontSize: '13px', cursor: 'pointer' }}
              onClick={() => navigate('/assets')}
            >
              资产管理
            </span>
            <span 
              style={{ color: 'var(--text-secondary)', fontSize: '13px', cursor: 'pointer' }}
              onClick={() => navigate('/reports')}
            >
              报告中心
            </span>
          </div>
        </div>
        
        <div style={{ display: 'flex', alignItems: 'center', gap: '24px' }}>
          <div style={{ 
            fontFamily: 'var(--font-mono)', 
            fontSize: '12px', 
            color: 'var(--text-secondary)',
            letterSpacing: '1px',
          }}>
            {currentTime.toISOString().split('T')[1].split('.')[0]} UTC
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--accent-green)', fontSize: '12px', fontWeight: '600' }}>
            <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: 'var(--accent-green)', animation: 'pulse 2s infinite' }} />
            SECURE
          </div>
          <BellOutlined style={{ color: 'var(--text-secondary)', fontSize: '16px', cursor: 'pointer' }} />
          <Dropdown menu={userMenu}>
            <Avatar 
              icon={<UserOutlined />} 
              style={{ background: 'var(--accent-cyan)', cursor: 'pointer' }}
            />
          </Dropdown>
        </div>
      </Header>

      <Layout>
        {/* Left Sidebar */}
        <Sider 
          width={180} 
          style={{ 
            background: 'var(--bg-secondary)',
            borderRight: '1px solid var(--border-subtle)',
            position: 'relative',
            zIndex: 10,
          }}
        >
          <Menu
            mode="inline"
            defaultSelectedKeys={['overview']}
            style={{ 
              height: '100%', 
              borderRight: 0,
              background: 'transparent',
            }}
            items={[
              {
                key: 'overview',
                icon: <DashboardOutlined style={{ color: 'var(--accent-cyan)' }} />,
                label: <span style={{ color: 'var(--text-primary)' }}>概览</span>,
                onClick: () => navigate('/'),
              },
              {
                key: 'projects',
                icon: <ProjectOutlined />,
                label: <span style={{ color: 'var(--text-secondary)' }}>项目管理</span>,
                onClick: () => navigate('/projects'),
              },
              {
                key: 'assets',
                icon: <DatabaseOutlined />,
                label: <span style={{ color: 'var(--text-secondary)' }}>资产管理</span>,
                onClick: () => navigate('/assets'),
              },
              {
                key: 'reports',
                icon: <FileTextOutlined />,
                label: <span style={{ color: 'var(--text-secondary)' }}>报告中心</span>,
                onClick: () => navigate('/reports'),
              },
              {
                key: 'settings',
                icon: <SettingOutlined />,
                label: <span style={{ color: 'var(--text-secondary)' }}>系统设置</span>,
                onClick: () => navigate('/settings/models'),
              },
            ]}
          />
        </Sider>

        {/* Main Content */}
        <Content style={{ padding: '12px', overflow: 'auto', position: 'relative', zIndex: 1 }}>          
          {/* Row 1: 合规分数趋势 (全宽) */}
          <div style={{ marginBottom: '8px' }}>
            <ErrorBoundary><ComplianceScoreTrend /></ErrorBoundary>
          </div>
          
          {/* Row 2: 活跃测评 + 资产分布 (两个等宽) */}
          <div className="argus-grid" style={{ gridTemplateColumns: 'repeat(2, 1fr)', marginBottom: '8px' }}>
            <ErrorBoundary><ActiveAssessments /></ErrorBoundary>
            <ErrorBoundary><AssetDistribution /></ErrorBoundary>
          </div>
          
          {/* Row 3: 风险热力图 (全宽) */}
          <div style={{ marginBottom: '8px' }}>
            <ErrorBoundary><RiskHeatmap /></ErrorBoundary>
          </div>
        </Content>
      </Layout>
    </Layout>
  );
};

export default Dashboard;
