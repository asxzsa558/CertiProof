import React, { useEffect, useState } from 'react';
import Card from '../Card';
import { RadialBarChart, RadialBar, ResponsiveContainer } from 'recharts';
import api from '../../services/api';
import { useNavigate } from 'react-router-dom';

const ActiveAssessments = ({ className }) => {
  const [data, setData] = useState(null);
  const navigate = useNavigate();

  useEffect(() => {
    const fetchData = async () => {
      try {
        const response = await api.get('/dashboard/argus/overview');
        setData(response.data);
      } catch (error) {
        console.error('Failed to fetch assessments:', error);
      }
    };
    fetchData();
  }, []);

  if (!data || !data.recent_projects) {
    return <Card title="活跃测评" live>Loading...</Card>;
  }

  const getRiskInfo = (score) => {
    if (score >= 75) return { level: 'low', label: '低风险', color: '#10b981' };
    if (score >= 50) return { level: 'medium', label: '中风险', color: '#f59e0b' };
    return { level: 'high', label: '高风险', color: '#ef4444' };
  };

  return (
    <Card title="活跃测评" live className={className}>
      <div style={{ marginBottom: '12px', fontSize: '9px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '1.5px' }}>
        {data.active_assessments || 0} 个进行中
      </div>
      
      <div style={{ 
        display: 'grid', 
        gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', 
        gap: '12px',
      }}>
        {data.recent_projects.length === 0 ? (
          <div style={{ color: 'var(--text-muted)', fontSize: '11px', padding: '16px 0', textAlign: 'center', gridColumn: '1 / -1' }}>
            暂无活跃测评
          </div>
        ) : (
          data.recent_projects.slice(0, 6).map((project) => {
            const score = project.compliance_score || 0;
            const riskInfo = getRiskInfo(score);
            
            // 准备径向进度条数据
            const progressData = [{
              name: 'progress',
              value: score,
              fill: riskInfo.color,
            }];
            
            return (
              <div 
                key={project.id}
                onClick={() => navigate(`/projects/${project.id}`)}
                style={{ 
                  padding: '16px', 
                  background: 'linear-gradient(135deg, rgba(0, 0, 0, 0.3), rgba(0, 0, 0, 0.1))',
                  borderRadius: '8px',
                  cursor: 'pointer',
                  transition: 'all 0.3s ease',
                  border: `1px solid ${riskInfo.color}30`,
                  boxShadow: `0 4px 12px rgba(0, 0, 0, 0.3), inset 0 1px 0 rgba(255, 255, 255, 0.05)`,
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.transform = 'perspective(1000px) rotateX(5deg) translateY(-4px)';
                  e.currentTarget.style.borderColor = `${riskInfo.color}60`;
                  e.currentTarget.style.boxShadow = `0 8px 24px rgba(0, 0, 0, 0.4), 0 0 20px ${riskInfo.color}30, inset 0 1px 0 rgba(255, 255, 255, 0.1)`;
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.transform = 'perspective(1000px) rotateX(0deg) translateY(0px)';
                  e.currentTarget.style.borderColor = `${riskInfo.color}30`;
                  e.currentTarget.style.boxShadow = '0 4px 12px rgba(0, 0, 0, 0.3), inset 0 1px 0 rgba(255, 255, 255, 0.05)';
                }}
              >
                <div style={{ marginBottom: '12px' }}>
                  <div style={{ 
                    fontSize: '13px', 
                    fontWeight: 600, 
                    color: 'var(--text-primary)', 
                    overflow: 'hidden', 
                    textOverflow: 'ellipsis', 
                    whiteSpace: 'nowrap',
                    marginBottom: '6px',
                  }}>
                    {project.name}
                  </div>
                  <div style={{ 
                    fontSize: '9px',
                    color: riskInfo.color,
                    textTransform: 'uppercase',
                    letterSpacing: '1px',
                    padding: '2px 6px',
                    background: `${riskInfo.color}15`,
                    borderRadius: '3px',
                    display: 'inline-block',
                    border: `1px solid ${riskInfo.color}30`,
                  }}>
                    {riskInfo.label}
                  </div>
                </div>
                
                {/* 径向进度条 */}
                <div style={{ height: '80px', marginBottom: '8px' }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <RadialBarChart 
                      cx="50%" 
                      cy="50%" 
                      innerRadius="60%" 
                      outerRadius="90%" 
                      barSize={8}
                      data={progressData}
                      startAngle={90}
                      endAngle={-270}
                    >
                      <RadialBar
                        background={{ fill: 'rgba(255, 255, 255, 0.05)' }}
                        dataKey="value"
                        cornerRadius={4}
                        animationDuration={1500}
                      />
                    </RadialBarChart>
                  </ResponsiveContainer>
                </div>
                
                <div style={{ 
                  textAlign: 'center',
                  fontSize: '24px',
                  fontWeight: 700,
                  fontFamily: 'var(--font-mono)',
                  color: riskInfo.color,
                  textShadow: `0 0 15px ${riskInfo.color}60`,
                }}>
                  {score}
                  <span style={{ fontSize: '12px', color: 'var(--text-muted)', marginLeft: '4px' }}>分</span>
                </div>
              </div>
            );
          })
        )}
      </div>
    </Card>
  );
};

export default ActiveAssessments;
