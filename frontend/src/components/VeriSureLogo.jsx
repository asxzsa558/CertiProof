import './VeriSureLogo.css'

function VeriSureLogo({ size = 56, className = '' }) {
  return (
    <div className={`logo-container ${className}`} style={{ width: size, height: size }}>
      <img src="/verisure-logo.svg" alt="VeriSure" className="logo-img" />
    </div>
  )
}

export default VeriSureLogo
