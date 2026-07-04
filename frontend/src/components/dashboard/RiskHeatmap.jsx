import React, { useEffect, useState } from 'react';
import Card from '../Card';
import api from '../../services/api';

const RiskHeatmap = ({ className }) => {
  const [data, setData] = useState(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const response = await api.get('/dashboard/argus/risk-heatmap');
        setData(response.data);
      } catch (error) {
        console.error('Failed to fetch risk heatmap:', error);
      }
    };
    fetchData();
  }, []);

  if (!data || !data.projects) {
    return <Card title="风险热力图">Loading...</Card>;
  }

  const getRiskColor = (value, severity) => {
    if (value === 0) return 'rgba(255, 255, 255, 0.02)';
    
    const colors = {
      critical: { base: '#dc2626', glow: 'rgba(220, 38, 38, 0.6)' },
      high: { base: '#ef4444', glow: 'rgba(239, 68, 68, 0.6)' },
      medium: { base: '#f59e0b', glow: 'rgba(245, 158, 11, 0.6)' },
      low: { base: '#10b981', glow: 'rgba(16, 185, 129, 0.6)' },
    };
    
    const intensity = Math.min(value / 10, 1); // 归一化到 0-1
    const color = colors[severity];
    
    return `linear-gradient(135deg, ${color.base}${Math.round(intensity * 60 + 20).toString(16).padStart(2, '0')}, ${color.base}${Math.round(intensity * 40 + 10).toString(16).padStart(2, '0')})`;
  };

  const getGlowEffect = (value, severity) => {
    if (value === 0) return 'none';
    
    const colors = {
      critical: 'rgba(220, 38, 38, 0.4)',
      high: 'rgba(239, 68, 68, 0.4)',
      medium: 'rgba(245, 158, 11, 0.4)',
      low: 'rgba(16, 185, 129, 0.4)',
    };
    
    const intensity = Math.min(value / 5, 1);
    return `0 0 ${8 + intensity * 12}px ${colors[severity]}`;
  };

  const totalRisks = data.projects.reduce((sum, p) => 
    sum + (p.critical || 0) + (p.high || 0) + (p.medium || 0) + (p.low || 0), 0);

  return (
    <Card title="风险热力图" live className={className}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px', marginBottom: '16px' }}>
        <span style={{ 
          fontSize: '24px', 
          fontWeight: '700', 
          color: totalRisks > 0 ? '#f59e0b' : '#10b981', 
          fontFamily: 'var(--font-mono)',
          lineHeight: 1,
          textShadow: totalRisks > 0 ? '0 0 20px rgba(245, 158, 11, 0.5)' : '0 0 20px rgba(16, 185, 129, 0.5)',
        }}>
          {totalRisks}
        </span>
        <span style={{ fontSize: '9px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '1.5px' }}>
          个风险
        </span>
      </div>
      
      {data.projects.length === 0 ? (
        <div style={{ color: 'var(--text-muted)', fontSize: '11px', padding: '16px 0', textAlign: 'center' }}>
          暂无风险数据
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          {/* 热力图矩阵 */}
          <div style={{ 
            display: 'grid', 
            gridTemplateColumns: '80px repeat(4, 1fr)',
            gap: '6px',
            fontSize: '10px',
          }}>
            {/* 表头 */}
            <div style={{ 
              padding: '8px',
              fontSize: '8px',
              color: 'var(--text-muted)',
              textTransform: 'uppercase',
              letterSpacing: '1px',
              fontWeight: 700,
            }}>
              项目
            </div>
            {['critical', 'high', 'medium', 'low'].map(severity => {
              const colors = {
                critical: '#dc2626',
                high: '#ef4444',
                medium: '#f59e0b',
                low: '#10b981',
              };
              const labels = {
                critical: '严重',
                high: '高',
                medium: '中',
                low: '低',
              };
              return (
                <div key={severity} style={{ 
                  padding: '8px',
                  fontSize: '8px',
                  color: colors[severity],
                  textTransform: 'uppercase',
                  letterSpacing: '1px',
                  fontWeight: 700,
                  textAlign: 'center',
                  textShadow: `0 0 10px ${colors[severity]}60`,
                }}>
                  {labels[severity]}
                </div>
              );
            })}
            
            {/* 数据行 */}
            {data.projects.map((project, idx) => (
              <React.Fragment key={idx}>
                <div style={{ 
                  padding: '8px',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '10px',
                  color: 'var(--text-secondary)',
                  display: 'flex',
                  alignItems: 'center',
                }}>
                  P-{project.project_id}
                </div>
                {['critical', 'high', 'medium', 'low'].map(severity => {
                  const value = project[severity] || 0;
                  return (
                    <div 
                      key={severity}
                      style={{ 
                        padding: '12px 8px',
                        background: getRiskColor(value, severity),
                        borderRadius: '4px',
                        border: value > 0 ? `1px solid ${severity === 'critical' ? '#dc262640' : severity === 'high' ? '#ef444440' : severity === 'medium' ? '#f59e0b40' : '#10b98140'}` : '1px solid rgba(255,255,255,0.05)',
                        textAlign: 'center',
                        fontSize: '14px',
                        fontWeight: 700,
                        fontFamily: 'var(--font-mono)',
                        color: value > 0 ? '#fff' : 'rgba(255,255,255,0.2)',
                        boxShadow: getGlowEffect(value, severity),
                        transition: 'all 0.3s ease',
                        cursor: value > 0 ? 'pointer' : 'default',
                      }}
                      onMouseEnter={(e) => {
                        if (value > 0) {
                          e.currentTarget.style.transform = 'scale(1.05)';
                        }
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.transform = 'scale(1)';
                      }}
                    >
                      {value > 0 ? value : '-'}
                    </div>
                  );
                })}
              </React.Fragment>
            ))}
          </div>
        </div>
      )}
      
      {/* 图例 */}
      <div style={{ 
        marginTop: '16px', 
        paddingTop: '12px', 
        borderTop: '1px solid var(--border-subtle)',
        display: 'flex',
        justifyContent: 'center',
        gap: '16px',
        fontSize: '9px',
      }}>
        {[
          { label: '严重', color: '#dc2626' },
          { label: '高', color: '#ef4444' },
          { label: '中', color: '#f59e0b' },
          { label: '低', color: '#10b981' },
        ].map(item => (
          <div key={item.label} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <div style={{
              width: '12px',
              height: '12px',
              borderRadius: '2px',
              background: `linear-gradient(135deg, ${item.color}60, ${item.color}30)`,
              border: `1px solid ${item.color}40`,
              boxShadow: `0 0 6px ${item.color}40`,
            }} />
            <span style={{ color: 'var(--text-secondary)' }}>{item.label}</span>
          </div>
        ))}
      </div>
    </Card>
  );
};

export default RiskHeatmap;
