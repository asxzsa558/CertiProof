import './VeriSureLogo.css'

function VeriSureLogo({ size = 56, className = '' }) {
  return (
    <div className={`logo-3d-container ${className}`} style={{ width: size, height: size }}>
      <img src="/verisure-logo.svg" alt="VeriSure" className="logo-3d" />
    </div>
  )
}

export default VeriSureLogo
