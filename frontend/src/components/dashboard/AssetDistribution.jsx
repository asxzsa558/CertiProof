import React, { useEffect, useState } from 'react';
import Card from '../Card';
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts';
import api from '../../services/api';

const AssetDistribution = ({ className }) => {
  const [data, setData] = useState(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const projectsResponse = await api.get('/dashboard/argus/overview');
        const projects = projectsResponse.data?.recent_projects || [];
        
        let allAssets = [];
        for (const project of projects) {
          try {
            const assetsResponse = await api.get(`/projects/${project.id}/assets/`);
            if (assetsResponse.data) {
              allAssets = allAssets.concat(assetsResponse.data);
            }
          } catch (error) {
            console.error(`Failed to fetch assets for project ${project.id}:`, error);
          }
        }
        
        const typeStats = {};
        allAssets.forEach(asset => {
          const type = asset.asset_type || 'unknown';
          typeStats[type] = (typeStats[type] || 0) + 1;
        });
        
        setData({
          total: allAssets.length,
          byType: typeStats,
        });
      } catch (error) {
        console.error('Failed to fetch assets:', error);
        setData({ total: 0, byType: {} });
      }
    };
    fetchData();
  }, []);

  if (!data) {
    return <Card title="资产分布">Loading...</Card>;
  }

  const typeLabels = { ip: 'IP 地址', domain: '域名', cloud_resource: '云资源' };
  const COLORS = ['#00d4ff', '#0ea5e9', '#f59e0b', '#10b981', '#ef4444', '#8b5cf6'];

  // 准备饼图数据
  const chartData = Object.entries(data.byType).map(([type, count]) => ({
    name: typeLabels[type] || type,
    value: count,
    type: type,
  }));

  return (
    <Card title="资产分布" live className={className}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '20px' }}>
        {/* Recharts 饼图 */}
        <div style={{ flex: '0 0 140px', height: '140px' }}>
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <defs>
                {COLORS.map((color, index) => (
                  <linearGradient key={`gradient-${index}`} id={`assetGrad-${index}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={color} stopOpacity={0.9}/>
                    <stop offset="100%" stopColor={color} stopOpacity={0.6}/>
                  </linearGradient>
                ))}
              </defs>
              <Pie
                data={chartData}
                cx="50%"
                cy="50%"
                outerRadius={60}
                innerRadius={30}
                paddingAngle={2}
                dataKey="value"
                animationBegin={0}
                animationDuration={1200}
              >
                {chartData.map((entry, index) => (
                  <Cell 
                    key={`cell-${index}`} 
                    fill={`url(#assetGrad-${index % COLORS.length})`}
                    stroke={COLORS[index % COLORS.length]}
                    strokeWidth={1}
                    style={{ 
                      filter: `drop-shadow(0 0 6px ${COLORS[index % COLORS.length]}60)`,
                    }}
                  />
                ))}
              </Pie>
              <Tooltip 
                contentStyle={{
                  background: 'rgba(10, 16, 32, 0.95)',
                  border: '1px solid rgba(0, 212, 255, 0.3)',
                  borderRadius: '4px',
                  fontSize: '11px',
                  boxShadow: '0 0 20px rgba(0, 212, 255, 0.2)',
                }}
                formatter={(value, name, props) => [
                  `${value} 个 (${Math.round((value / data.total) * 100)}%)`,
                  name
                ]}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>
        
        {/* 自定义图例 */}
        <div style={{ flex: 1 }}>
          <div style={{ 
            display: 'flex', 
            flexDirection: 'column', 
            gap: '8px',
            fontSize: '10px',
          }}>
            {chartData.map((item, index) => (
              <div key={`legend-${index}`} style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <div style={{
                  width: '10px',
                  height: '10px',
                  borderRadius: '2px',
                  background: COLORS[index % COLORS.length],
                  boxShadow: `0 0 6px ${COLORS[index % COLORS.length]}60`,
                }} />
                <span style={{ color: 'var(--text-secondary)', flex: 1 }}>
                  {item.name}
                </span>
                <span style={{ 
                  color: COLORS[index % COLORS.length],
                  fontFamily: 'var(--font-mono)',
                  fontWeight: 600,
                }}>
                  {item.value} ({Math.round((item.value / data.total) * 100)}%)
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
      
      {/* 总数统计 */}
      <div style={{ 
        marginTop: '16px', 
        paddingTop: '12px', 
        borderTop: '1px solid var(--border-subtle)',
        textAlign: 'center',
      }}>
        <div style={{ 
          fontSize: '9px', 
          color: 'var(--text-muted)', 
          textTransform: 'uppercase', 
          letterSpacing: '1.5px',
          marginBottom: '6px',
        }}>
          总资产数
        </div>
        <div style={{ 
          fontSize: '28px', 
          fontWeight: 700, 
          color: 'var(--accent-cyan)',
          fontFamily: 'var(--font-mono)',
          textShadow: '0 0 20px rgba(0, 212, 255, 0.5)',
        }}>
          {data.total}
        </div>
      </div>
    </Card>
  );
};

export default AssetDistribution;
