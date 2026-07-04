import React from 'react';
import '../styles/theme.css';

const ProgressBar = ({ value, riskLevel = 'low', className = '' }) => {
  const clampedValue = Math.max(0, Math.min(100, value));
  
  return (
    <div className={`argus-progress ${className}`}>
      <div 
        className={`argus-progress-fill ${riskLevel !== 'low' ? `risk-${riskLevel}` : ''}`}
        style={{ width: `${clampedValue}%` }}
      />
    </div>
  );
};

export default ProgressBar;
