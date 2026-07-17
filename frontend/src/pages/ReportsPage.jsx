import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Avatar, Button, Dropdown, Modal, Select, Tag, Tooltip, message } from 'antd'
import {
  ArrowLeftOutlined,
  BarChartOutlined,
  CheckCircleFilled,
  DownloadOutlined,
  ExclamationCircleFilled,
  FileTextOutlined,
  LogoutOutlined,
  ProjectOutlined,
  EyeOutlined,
  SafetyCertificateOutlined,
  UserOutlined,
} from '@ant-design/icons'
import api from '../services/api'
import { useAuthStore } from '../store/authStore'
import VeriSureLogo from '../components/VeriSureLogo'
import './Dashboard.css'
import './ReportsPage.css'

const reportState = (project) => {
  const progress = Number(project.progress || 0)
  const risks = Number(project.risk_count || 0)
  const total = Number(project.task_total || 0)
  const done = Number(project.task_done || 0)
  const artifact = project.report || {}
  if (artifact.available && artifact.stale) {
    return { label: `报告 V${artifact.version} 已过期`, tone: 'attention', detail: artifact.stale_reason || '测评数据已变化，请重新生成' }
  }
  if (artifact.available) {
    return {
      label: `正式报告 V${artifact.version}`,
      tone: risks > 0 ? 'attention' : 'ready',
      detail: risks > 0 ? `报告如实保留 ${risks} 项待处理风险` : '当前版本与测评数据一致',
    }
  }
  if (risks > 0) return { label: '存在待处理风险', tone: 'attention', detail: `${risks} 项风险尚未解决` }
  if (!total) return { label: '尚未测评', tone: 'idle', detail: '尚无测评任务结果' }
  if (progress >= 100 && done < total) return { label: '测评进度待校正', tone: 'attention', detail: `显示 ${progress}% ，但仅完成 ${done}/${total} 项任务` }
  if (progress >= 100) return { label: '等待生成正式报告', tone: 'progress', detail: '请在项目测评最后阶段生成' }
  return { label: '测评进行中', tone: 'progress', detail: `${done}/${total} 项任务已完成` }
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
  const [previewingId, setPreviewingId] = useState(null)
  const [preview, setPreview] = useState(null)

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
    reportState: reportState(project),
  }))

  const handleDownloadReport = async (projectId) => {
    setDownloadingId(projectId)
    try {
      const response = await api.get(`/projects/${projectId}/report`, { responseType: 'blob' })
      const url = window.URL.createObjectURL(new Blob([response.data]))
      const link = document.createElement('a')
      link.href = url
      link.setAttribute('download', `certiproof-report-${projectId}.html`)
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch (error) {
      console.error('Failed to download report:', error)
      message.error(error.response?.data?.detail || '报告下载失败')
    } finally {
      setDownloadingId(null)
    }
  }

  const handlePreviewReport = async (projectId) => {
    setPreviewingId(projectId)
    try {
      const response = await api.get(`/projects/${projectId}/report`, { responseType: 'text' })
      setPreview({ html: response.data, projectId })
    } catch (error) {
      console.error('Failed to preview report:', error)
      message.error(error.response?.data?.detail || '报告预览失败')
    } finally {
      setPreviewingId(null)
    }
  }

  const closePreview = () => setPreview(null)

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
          <span>CertiProof</span>
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
            <p>以当前待处理风险、已执行检测和文档证据为依据生成可追溯的等保自查报告。</p>
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
            <div><strong>{reports.length}</strong><em>测评项目</em></div>
          </div>
          <div className="org-kpi">
            <span><SafetyCertificateOutlined /></span>
            <div><strong>{dashboard.summary.average_progress || 0}%</strong><em>平均进度</em></div>
          </div>
          <div className="org-kpi">
            <span><CheckCircleFilled /></span>
            <div><strong>{reports.filter((item) => item.report?.available).length}</strong><em>正式报告</em></div>
          </div>
          <div className="org-kpi">
            <span><ExclamationCircleFilled /></span>
            <div><strong>{reports.filter((item) => item.reportState.tone === 'attention').length}</strong><em>需整改项目</em></div>
          </div>
        </section>

        <section className="org-panel report-board">
          <div className="org-panel-head">
            <h2>项目报告矩阵</h2>
            <span>{loading ? '同步中' : `${reports.length} 个项目`}</span>
          </div>

          <div className="report-list scroll-region scroll-fade">
            {reports.length ? reports.map((report) => (
              <article className={`report-item ${report.reportState.tone}`} key={report.project_id}>
                <div className="report-item-head">
                  <span className="report-id">P-{String(report.project_id).padStart(3, '0')}</span>
                  <h3>{report.name}</h3>
                  <Tag color={report.level === '三级' ? 'red' : 'blue'}>{report.level || '未定级'}</Tag>
                </div>
                <div className="report-item-state"><span className={`report-state-dot ${report.reportState.tone}`} /><div><strong>{report.reportState.label}</strong><p>{report.reportState.detail}</p></div></div>
                <div className="report-item-progress"><div><span>{report.stage || '尚未开始'}</span><em>{report.progress || 0}%</em></div><div className="mini-progress"><b style={{ width: `${report.progress || 0}%` }} /></div></div>
                <dl className="report-item-metrics"><div><dt>测评任务</dt><dd>{report.task_done || 0}/{report.task_total || 0}</dd></div><div><dt>待处理风险</dt><dd className={report.risk_count ? 'hot' : ''}>{report.risk_count || 0}</dd></div><div><dt>正式报告</dt><dd>{report.report?.available ? `V${report.report.version}${report.report.stale ? ' · 已过期' : ''}` : '尚未生成'}</dd></div></dl>
                <div className="report-actions">
                  <Button
                    size="small"
                    icon={<EyeOutlined />}
                    loading={previewingId === report.project_id}
                    onClick={() => handlePreviewReport(report.project_id)}
                    disabled={!report.report?.available}
                  >
                    {report.report?.stale ? '查看旧版本' : '预览'}
                  </Button>
                  <Tooltip title="下载 HTML 报告">
                    <Button
                      size="small"
                      icon={<DownloadOutlined />}
                      loading={downloadingId === report.project_id}
                      onClick={() => handleDownloadReport(report.project_id)}
                      aria-label="下载 HTML 报告"
                      disabled={!report.report?.available}
                    />
                  </Tooltip>
                </div>
              </article>
            )) : (
              <div className="empty-panel">暂无项目报告。创建项目并完成测评后会在这里汇总。</div>
            )}
          </div>
        </section>
      </main>
      <Modal className="report-preview-modal" open={Boolean(preview)} title="报告预览" width="min(1280px, calc(100vw - 40px))" footer={null} onCancel={closePreview} destroyOnHidden>
        {preview ? <iframe className="report-preview-frame" title={`报告预览-${preview.projectId}`} sandbox="" srcDoc={preview.html} /> : null}
      </Modal>
    </div>
  )
}

export default ReportsPage
