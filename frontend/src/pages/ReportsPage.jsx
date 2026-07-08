import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Avatar, Button, Dropdown, Select, Tag, message } from 'antd'
import {
  ArrowLeftOutlined,
  BarChartOutlined,
  CheckCircleFilled,
  DownloadOutlined,
  FileTextOutlined,
  LogoutOutlined,
  ProjectOutlined,
  SafetyCertificateOutlined,
  UserOutlined,
} from '@ant-design/icons'
import api from '../services/api'
import { useAuthStore } from '../store/authStore'
import VeriSureLogo from '../components/VeriSureLogo'
import './Dashboard.css'
import './ReportsPage.css'

const statusText = (progress) => {
  if (progress >= 100) return '可归档'
  if (progress >= 60) return '待复核'
  return '生成中'
}

function ReportsPage() {
  const navigate = useNavigate()
  const user = useAuthStore((state) => state.user)
  const logout = useAuthStore((state) => state.logout)
  const organizations = useAuthStore((state) => state.organizations)
  const currentOrgId = useAuthStore((state) => state.currentOrgId)
  const setCurrentOrg = useAuthStore((state) => state.setCurrentOrg)
  const [dashboard, setDashboard] = useState({ summary: {}, project_matrix: [], risk_queue: [] })
  const [loading, setLoading] = useState(false)
  const [downloadingId, setDownloadingId] = useState(null)

  const currentOrg = useMemo(
    () => organizations.find((org) => org.id === currentOrgId) || organizations[0],
    [organizations, currentOrgId]
  )

  useEffect(() => {
    const fetchReports = async () => {
      if (!currentOrg?.id) return
      setLoading(true)
      try {
        const response = await api.get('/dashboard/organization-command', { params: { organization_id: currentOrg.id } })
        setDashboard({
          summary: response.data?.summary || {},
          project_matrix: response.data?.project_matrix || [],
          risk_queue: response.data?.risk_queue || [],
        })
      } catch (error) {
        console.error('Failed to fetch reports:', error)
        message.error('报告中心加载失败')
      } finally {
        setLoading(false)
      }
    }

    fetchReports()
  }, [currentOrg?.id])

  const reports = dashboard.project_matrix.map((project) => ({
    ...project,
    status: statusText(project.progress || 0),
    blocked: (project.risk_count || 0) > 0,
  }))

  const handleDownloadReport = async (projectId) => {
    setDownloadingId(projectId)
    try {
      const response = await api.get(`/projects/${projectId}/report`, { responseType: 'blob' })
      const url = window.URL.createObjectURL(new Blob([response.data]))
      const link = document.createElement('a')
      link.href = url
      link.setAttribute('download', `certiproof-report-${projectId}.pdf`)
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch (error) {
      console.error('Failed to download report:', error)
      message.error('报告下载失败')
    } finally {
      setDownloadingId(null)
    }
  }

  const userMenu = {
    items: [
      {
        key: 'logout',
        icon: <LogoutOutlined />,
        label: '退出登录',
        onClick: logout,
      },
    ],
  }

  return (
    <div className="org-dashboard reports-dashboard">
      <aside className="org-sidebar">
        <button type="button" className="reports-back" onClick={() => navigate('/dashboard')}>
          <ArrowLeftOutlined /> 返回 Dashboard
        </button>
        <div className="org-brand">
          <VeriSureLogo size={52} />
          <span>VeriSure</span>
        </div>
        <nav className="org-nav">
          <div className="org-nav-group">
            <em>治理中心</em>
            <button type="button" className="active">
              <FileTextOutlined /> 报告中心
            </button>
            <button type="button" onClick={() => navigate('/projects')}>
              <ProjectOutlined /> 项目工作台
            </button>
            <button type="button" onClick={() => navigate('/dashboard')}>
              <BarChartOutlined /> 全局态势
            </button>
          </div>
        </nav>
      </aside>

      <main className="org-main">
        <header className="org-topbar">
          <div>
            <h1>报告中心</h1>
            <p>按项目汇总等保测评进度、测评任务、证据数量、风险阻塞项和报告导出状态。</p>
          </div>
          <div className="org-top-actions">
            <Select
              className="org-select"
              value={currentOrg?.id}
              onChange={setCurrentOrg}
              options={organizations.map((org) => ({ value: org.id, label: org.name }))}
            />
            <Dropdown menu={userMenu} placement="bottomRight">
              <Avatar className="org-avatar" icon={<UserOutlined />}>
                {user?.username?.[0]?.toUpperCase()}
              </Avatar>
            </Dropdown>
          </div>
        </header>

        <section className="report-kpis">
          <div className="org-kpi">
            <span><FileTextOutlined /></span>
            <div><strong>{reports.length}</strong><em>项目报告</em></div>
          </div>
          <div className="org-kpi">
            <span><SafetyCertificateOutlined /></span>
            <div><strong>{dashboard.summary.average_progress || 0}%</strong><em>平均进度</em></div>
          </div>
          <div className="org-kpi">
            <span><CheckCircleFilled /></span>
            <div><strong>{reports.filter((item) => item.progress >= 100).length}</strong><em>可归档</em></div>
          </div>
          <div className="org-kpi">
            <span><BarChartOutlined /></span>
            <div><strong>{dashboard.risk_queue.length}</strong><em>风险阻塞</em></div>
          </div>
        </section>

        <section className="org-panel report-board">
          <div className="org-panel-head">
            <h2>项目报告矩阵</h2>
            <span>{loading ? '同步中' : `${reports.length} 份`}</span>
          </div>

          <div className="report-table scroll-region">
            <div className="report-row report-head">
              <span>项目</span>
              <span>等级</span>
              <span>阶段</span>
              <span>进度</span>
              <span>风险</span>
              <span>测评任务</span>
              <span>状态</span>
              <span>操作</span>
            </div>
            {reports.length ? reports.map((report) => (
              <div className="report-row" key={report.project_id}>
                <strong>{report.name}</strong>
                <Tag color={report.level === '三级' ? 'red' : 'blue'}>{report.level}</Tag>
                <span>{report.stage}</span>
                <div className="mini-progress">
                  <b style={{ width: `${report.progress || 0}%` }} />
                  <em>{report.progress || 0}%</em>
                </div>
                <span className={report.risk_count ? 'report-risk hot' : 'report-risk'}>{report.risk_count}</span>
                <span>{report.task_done || 0}/{report.task_total || 0}</span>
                <Tag color={report.blocked ? 'gold' : report.progress >= 100 ? 'green' : 'blue'}>{report.status}</Tag>
                <Button
                  size="small"
                  icon={<DownloadOutlined />}
                  loading={downloadingId === report.project_id}
                  onClick={() => handleDownloadReport(report.project_id)}
                >
                  PDF
                </Button>
              </div>
            )) : (
              <div className="empty-panel">暂无项目报告。创建项目并完成测评后会在这里汇总。</div>
            )}
          </div>
        </section>
      </main>
    </div>
  )
}

export default ReportsPage
