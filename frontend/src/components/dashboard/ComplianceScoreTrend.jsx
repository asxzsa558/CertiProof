import React, { useEffect, useState } from 'react';
import Card from '../Card';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import api from '../../services/api';

const ComplianceScoreTrend = ({ className }) => {
  const [data, setData] = useState(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const response = await api.get('/dashboard/argus/score-trend?days=30');
        setData(response.data);
      } catch (error) {
        console.error('Failed to fetch score trend:', error);
      }
    };
    fetchData();
  }, []);

  if (!data || !data.scores) {
    return <Card title="合规分数趋势">Loading...</Card>;
  }

  const avgScore = data.scores.length > 0 
    ? Math.round(data.scores.reduce((sum, s) => sum + s.score, 0) / data.scores.length)
    : 0;

  const getGrade = (score) => {
    if (score >= 90) return { label: '优秀', color: '#10b981' };
    if (score >= 75) return { label: '良好', color: '#00d4ff' };
    if (score >= 60) return { label: '一般', color: '#f59e0b' };
    return { label: '危险', color: '#ef4444' };
  };

  const grade = getGrade(avgScore);

  // 准备图表数据
  const chartData = data.scores.map((s, idx) => ({
    day: idx + 1,
    score: s.score,
    name: s.project_name,
  }));

  return (
    <Card title="合规分数趋势" live className={className}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '24px', marginBottom: '20px' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px' }}>
            <span style={{ 
              fontSize: '42px', 
              fontWeight: '700', 
              color: grade.color, 
              fontFamily: 'var(--font-mono)',
              lineHeight: 1,
              textShadow: `0 0 30px ${grade.color}80`,
            }}>
              {avgScore}
            </span>
            <span style={{ fontSize: '14px', color: 'var(--text-secondary)' }}>/100</span>
          </div>
          <div style={{ marginTop: '8px', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{
              fontSize: '10px',
              fontWeight: 700,
              color: grade.color,
              textTransform: 'uppercase',
              letterSpacing: '1.5px',
              padding: '3px 10px',
              borderRadius: '3px',
              background: `${grade.color}25`,
              border: `1px solid ${grade.color}50`,
              boxShadow: `0 0 10px ${grade.color}40`,
            }}>
              {grade.label}
            </span>
          </div>
        </div>
      </div>
      
      {/* Recharts 面积图 */}
      <div style={{ height: '120px', marginBottom: '16px' }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData} margin={{ top: 5, right: 5, left: 5, bottom: 5 }}>
            <defs>
              <linearGradient id="colorScore" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={grade.color} stopOpacity={0.8}/>
                <stop offset="95%" stopColor={grade.color} stopOpacity={0.1}/>
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
            <XAxis 
              dataKey="day" 
              stroke="rgba(255,255,255,0.3)" 
              fontSize={9}
              tick={{ fill: 'rgba(255,255,255,0.5)' }}
            />
            <YAxis 
              stroke="rgba(255,255,255,0.3)" 
              fontSize={9}
              tick={{ fill: 'rgba(255,255,255,0.5)' }}
              domain={[0, 100]}
            />
            <Tooltip 
              contentStyle={{
                background: 'rgba(10, 16, 32, 0.95)',
                border: `1px solid ${grade.color}40`,
                borderRadius: '4px',
                fontSize: '11px',
                boxShadow: `0 0 20px ${grade.color}30`,
              }}
              labelStyle={{ color: 'rgba(255,255,255,0.7)' }}
              itemStyle={{ color: grade.color }}
            />
            <Area 
              type="monotone" 
              dataKey="score" 
              stroke={grade.color}
              strokeWidth={2}
              fillOpacity={1} 
              fill="url(#colorScore)"
              style={{ filter: `drop-shadow(0 0 8px ${grade.color}60)` }}
              animationDuration={1500}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      
      {/* 项目分数列表 */}
      <div style={{ paddingTop: '16px', borderTop: '1px solid var(--border-subtle)' }}>
        <div style={{ fontSize: '9px', color: 'var(--text-muted)', marginBottom: '10px', textTransform: 'uppercase', letterSpacing: '1.5px' }}>
          项目分数明细
        </div>
        {data.scores.length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {data.scores.map((score, idx) => {
              const sGrade = getGrade(score.score);
              return (
                <div key={idx} style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '11px' }}>
                  <span style={{ color: 'var(--text-secondary)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {score.project_name}
                  </span>
                  <div style={{ width: '100px', height: '4px', background: 'var(--bg-tertiary)', borderRadius: '2px', overflow: 'hidden' }}>
                    <div style={{ 
                      width: `${score.score}%`, 
                      height: '100%', 
                      background: `linear-gradient(90deg, ${sGrade.color}, ${sGrade.color}80)`,
                      boxShadow: `0 0 8px ${sGrade.color}`,
                      transition: 'width 1s ease-out',
                    }} />
                  </div>
                  <span style={{ 
                    color: sGrade.color, 
                    fontFamily: 'var(--font-mono)', 
                    fontWeight: 700, 
                    minWidth: '35px', 
                    textAlign: 'right',
                    textShadow: `0 0 10px ${sGrade.color}60`,
                  }}>
                    {Math.round(score.score)}
                  </span>
                </div>
              );
            })}
          </div>
        ) : (
          <div style={{ color: 'var(--text-muted)', fontSize: '11px', padding: '12px 0', textAlign: 'center' }}>
            暂无分数数据
          </div>
        )}
      </div>
    </Card>
  );
};

export default ComplianceScoreTrend;
