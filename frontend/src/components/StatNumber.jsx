import React from 'react';
import '../styles/theme.css';

const StatNumber = ({ value, label, change, changeType = 'up' }) => {
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px' }}>
        <span className="stat-number">{value}</span>
        {change !== undefined && (
          <span className={`stat-change ${changeType}`}>
            {changeType === 'up' ? '↑' : '↓'} {change}
          </span>
        )}
      </div>
      {label && <div className="stat-label">{label}</div>}
    </div>
  );
};

export default StatNumber;
