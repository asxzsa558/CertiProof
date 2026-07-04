import React from 'react';
import '../styles/theme.css';

const RiskBadge = ({ level, children }) => {
  const validLevels = ['critical', 'high', 'medium', 'low', 'info'];
  const riskLevel = validLevels.includes(level) ? level : 'info';
  
  return (
    <span className={`risk-badge ${riskLevel}`}>
      {children || riskLevel}
    </span>
  );
};

export default RiskBadge;
